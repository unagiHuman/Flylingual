"""Local Bridge: one Brain owner, separate control/audio and motor transports."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import copy
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import signal
import time
import uuid

from aiohttp import web, WSMsgType

from .brain_adapter import BrainAdapter, BrainAdapterError
from .config import load_config
from .control import ControlArbiter, ControlError
from .conversation import ConversationAdapter, ConversationError
from .conversation_settings import SettingsError, options_message, validate_settings
from .translation import message_text, summarize


class Bridge:
    def __init__(self, config):
        self.config = config
        self.arbiter = ControlArbiter(config['control'])
        self.adapter = None
        self.target = config['brain']
        self.profile = config['profile']
        self.conversation = ConversationAdapter(config['conversation'], self.conversation_event, self.voice_utterance)
        self.control_ws = None
        self.control_queue = None
        self.motor_writer = None
        self.motor_queue = None
        self.unity_generation = 0
        self.request_counter = 0
        self.requests = OrderedDict()
        self.input_ids = OrderedDict()
        self.intent_tasks = set()
        self.tasks = set()
        self.switching = False
        self.release_unknown = False
        self.stop_request = None
        self.stop_applied = False
        self.frame = None
        self.last_summary = 0
        self.last_spoken_state = None
        self.intent_revision = 0
        self.conversation_announced = False
        self.voice_control_epoch = None
        self.conversation_settings_revision = 0
        self.settings_request_ids = OrderedDict()
        self.conversation_interaction = 'control'  # Legacy clients keep conservative semantics.
        self.conversation_generation = 0
        self.conversation_accepting = False
        self.conversation_operation = None
        self.brain_identity = None
        self.closed = False
        self.log_file = None

    def log(self, event, **fields):
        if self.log_file:
            self.log_file.info(json.dumps({'event': event, 'monotonicMs': round(time.monotonic()*1000, 3),
                                            'epoch': self.arbiter.epoch, **fields},
                                           ensure_ascii=False, allow_nan=False))

    def task(self, coroutine, intent=False):
        task = asyncio.create_task(coroutine)
        collection = self.intent_tasks if intent else self.tasks
        collection.add(task)
        def done(finished):
            collection.discard(finished)
            if not finished.cancelled() and finished.exception() is not None:
                self.log('background_failed', error=type(finished.exception()).__name__)
                exc = finished.exception()
                self.emit({'type': 'error', 'error': str(exc) if isinstance(exc, (ControlError, ConversationError)) else 'operation_failed'})
        task.add_done_callback(done)
        return task

    def age_ms(self):
        if self.frame is None or self.adapter is None:
            return None
        return max(0, (time.monotonic() - self.adapter.latest_received_at)*1000)

    def summary(self):
        return summarize(self.frame, self.age_ms(), self.config['control']['staleMs'], self.conversation.settings['language'])

    def text(self, key):
        return message_text(key, self.conversation.settings['language'])

    def state(self):
        status = self.adapter.status if self.adapter else {}
        return {'type': 'bridge_state', 'epoch': self.arbiter.epoch,
                'owner': self.arbiter.owner, 'outputInhibited': self.arbiter.inhibited,
                'reason': self.arbiter.reason, 'profile': self.profile,
                'target': {'host': self.target['host'], 'port': self.target['port']},
                'brainConnected': bool(self.adapter and self.adapter.connected), 'brainReady': False,
                'conversationState': self.conversation.state, 'conversationMode': self.conversation.mode,
                'capabilities': ['conversation_only_v1'],
                'conversationInteraction': self.conversation_interaction,
                'conversationGeneration': self.conversation_generation,
                'audioDiagnostics': self.conversation.diagnostics(),
                'conversationSettings': dict(self.conversation.settings),
                'conversationSettingsRevision': self.conversation_settings_revision,
                'resumeReady': self.resume_ready(),
                'voiceControlAvailable': self.voice_control_epoch == self.arbiter.epoch,
                'frameAgeMs': self.age_ms(), 'switching': self.switching,
                'releaseUnknown': self.release_unknown, 'executionOS': platform.system(),
                'backend': status.get('backendId'), 'dataset': status.get('datasetId'),
                'configHash': status.get('configHash'), 'graphHash': status.get('graphHash'),
                'sourceHash': status.get('sourceHash'), 'sessionId': status.get('sessionId'),
                'instanceId': status.get('instanceId'), 'activeControllerCount': status.get('activeControllerCount'),
                'brainMode': 'LIVE', 'ready': False}

    def emit(self, event):
        if event.get('type') in ('audio', 'conversation_text', 'conversation_state', 'discard_audio'):
            event = {**event, 'conversationGeneration': self.conversation_generation}
        queue = self.control_queue
        if queue is not None:
            if queue.full():
                # A slow audio/UI consumer cannot stall the Brain reader. Close
                # it so client-side output inhibition takes effect.
                if self.control_ws is not None:
                    self.task(self.control_ws.close(code=1013, message=b'slow_consumer'))
                return
            queue.put_nowait(event)

    def motor_emit(self, event):
        queue = self.motor_queue
        if queue is not None:
            if queue.full():
                if self.motor_writer is not None:
                    self.motor_writer.close()
                return
            queue.put_nowait(event)

    def invalidate(self, preserve_conversation=False):
        self.intent_revision += 1
        for task in tuple(self.intent_tasks):
            if task is not asyncio.current_task():
                task.cancel()
        if not preserve_conversation:
            self.conversation.clear_context()
        self.last_spoken_state = None
        self.conversation_announced = False
        self.voice_control_epoch = None
        if not preserve_conversation:
            self.emit({'type': 'discard_audio', 'epoch': self.arbiter.epoch})

    async def inhibit(self, reason, send_stop=True):
        self.arbiter.inhibit(reason)
        # Physical safety events cannot end general chat in the native mode.
        # No Brain observations are fed into that session (UI still shows them).
        self.invalidate(preserve_conversation=self.conversation_interaction == 'chat_only')
        self.emit(self.state())
        self.log('output_inhibited', reason=reason)
        # Never synthesize a zero BrainFrame: downstream audio/control adapters
        # must obey outputInhibited; legacy motor clients receive EOF as well.
        if self.motor_writer is not None:
            self.motor_writer.close()
        if send_stop and self.adapter and self.adapter.connected:
            try:
                await self.submit('STOP', 'safety', 'safety-' + str(uuid.uuid4()))
            except (BrainAdapterError, ConnectionError, OSError):
                self.log('stop_send_failed')

    async def submit(self, action, source, command_id, unity_id=None):
        if self.conversation_interaction == 'chat_only' and source != 'safety':
            raise ControlError('chat_only_cannot_control')
        if not self.adapter or not self.adapter.connected:
            raise ControlError('brain_disconnected')
        self.request_counter += 1
        request_id = self.request_counter
        item = {'source': source, 'commandId': command_id, 'action': action,
                'epoch': self.arbiter.epoch, 'unityId': unity_id,
                'unityGeneration': self.unity_generation, 'sent': time.monotonic(), 'applied': False}
        self.requests[request_id] = item
        while len(self.requests) > 4096:
            self.requests.popitem(last=False)
        if action == 'STOP':
            self.stop_request = request_id
            self.stop_applied = False
        self.log('command_submitted', requestId=request_id, commandId=command_id, action=action, source=source)
        await self.adapter.send_action(action, request_id)
        self.emit({'type': 'command_result', 'stage': 'submitted', 'commandId': command_id,
                   'requestId': request_id, 'action': action, 'epoch': self.arbiter.epoch,
                   'message': self.text('submitted')})
        return request_id

    def require_fresh(self):
        if not self.adapter or not self.adapter.connected or self.summary()['stale']:
            raise ControlError('fresh_brain_required')

    async def brain_message(self, event):
        kind = event['type']
        if kind == 'status':
            identity = tuple(event.get(k) for k in ('instanceId', 'sessionId', 'backendId', 'datasetId'))
            if self.brain_identity is not None and identity != self.brain_identity:
                self.stop_conversation_session()
            self.brain_identity = identity
            self.log('brain_identity', **{k: event.get(k) for k in (
                'instanceId', 'sessionId', 'backendId', 'datasetId', 'sourceHash', 'configHash',
                'graphHash', 'activeControllerCount')})
            self.emit(self.state())
        elif kind == 'brain_frame':
            self.frame = event
            rid = event.get('appliedRequestId')
            item = self.requests.get(rid)
            if rid == self.stop_request:
                self.stop_applied = True
            if item and not item['applied'] and item['epoch'] == self.arbiter.epoch:
                item['applied'] = True
                latency = (time.monotonic()-item['sent'])*1000
                for older_id, older in self.requests.items():
                    if older_id < rid and not older['applied'] and not older.get('superseded'):
                        older['superseded'] = True
                        self.log('command_superseded', requestId=older_id, commandId=older['commandId'])
                self.log('command_applied', requestId=rid, commandId=item['commandId'], sequence=event['sequence'], e2eMs=latency)
                self.emit({'type': 'command_result', 'stage': 'brain_applied', 'commandId': item['commandId'],
                           'requestId': rid, 'action': item['action'], 'e2eMs': latency,
                           'message': self.text('applied')})
            self.emit(event)
            # Preserve the original upstream request ID and unmodified neural
            # values. Bounded rotation prevents unlimited raw-frame accumulation.
            self.log('frame', frame=event)
            if not self.arbiter.inhibited and self.motor_writer:
                outgoing = copy.deepcopy(event)
                outgoing['appliedRequestId'] = (item['unityId'] if item and item['source'] == 'manual_tcp'
                    and item['epoch'] == self.arbiter.epoch and item['unityGeneration'] == self.unity_generation else 0)
                self.motor_emit(outgoing)
        elif kind == 'ack':
            item = self.requests.get(event['requestId'])
            if item and item['epoch'] == self.arbiter.epoch:
                self.log('command_accepted', requestId=event['requestId'], commandId=item['commandId'], accepted=event['accepted'])
                self.emit({'type': 'command_result', 'stage': 'accepted', 'commandId': item['commandId'],
                           'requestId': event['requestId'], 'accepted': event['accepted']})
                if item['source'] == 'manual_tcp' and item['unityGeneration'] == self.unity_generation:
                    self.motor_emit({**event, 'requestId': item['unityId']})
        elif kind in ('error', 'adapter_error'):
            await self.inhibit('brain_transport_error', send_stop=False)
            self.emit({'type': 'error', 'error': 'brain_transport_error'})

    async def connect_brain(self, target):
        self.frame = None
        self.stop_applied = False
        adapter = BrainAdapter(self.brain_message)
        self.adapter = adapter
        await adapter.connect(target)
        await self.submit('STOP', 'safety', 'connect-stop-' + str(uuid.uuid4()))

    def stopped_fresh(self):
        summary = self.summary()
        if summary['stale'] or not self.stop_applied or not self.frame:
            return False
        motor = self.frame['motor']
        return motor['forward'] <= .02 and abs(motor['turn']) <= .02

    def resume_ready(self):
        return (self.conversation_interaction != 'chat_only'
                and self.arbiter.inhibited and bool(self.adapter and self.adapter.connected)
                and not self.switching and not self.release_unknown
                and self.arbiter.owner != 'observer'
                and (self.arbiter.owner != 'gpt' or self.conversation.state in ('live', 'mock'))
                and self.stopped_fresh())

    async def switch_target(self, profile):
        if self.switching or self.release_unknown:
            raise ControlError('switch_unavailable')
        if profile not in ('mac-local', 'windows-local', 'windows-to-mac', 'mac-to-windows'):
            raise ControlError('unknown_profile')
        target = load_config(profile, local=self.config.get('_localPath'))['brain']
        self.switching = True
        try:
            self.stop_conversation_session()
            await self.inhibit('switching')
            self.log('switch_stage', stage='release_old')
            if self.adapter:
                try:
                    evidence = await self.adapter.release()
                    self.log('controller_released', **evidence)
                except Exception:
                    self.release_unknown = True
                    self.arbiter.reason = 'release_unknown'
                    raise ControlError('release_unknown') from None
            self.requests.clear()
            self.frame = None
            self.target = target
            self.profile = profile
            self.log('switch_stage', stage='connect_new', profile=profile)
            await self.connect_brain(target)
            deadline = time.monotonic() + self.config['control']['stopTimeoutMs']/1000
            while not self.stopped_fresh():
                if time.monotonic() >= deadline:
                    raise ControlError('stop_confirmation_timeout')
                await asyncio.sleep(.05)
            self.arbiter.reason = 'explicit_resume_required'
            self.log('switch_stage', stage='stopped_waiting_resume')
            self.task(self.conversation.append('instructions', self.text('target_changed')))
        except Exception as exc:
            if not self.release_unknown:
                self.arbiter.reason = 'switch_failed'
            self.emit({'type': 'error', 'error': self.arbiter.reason})
            self.log('switch_failed', error=type(exc).__name__)
        finally:
            self.switching = False
            self.emit(self.state())

    async def conversation_event(self, event):
        if (self.conversation_interaction == 'chat_only'
                and event['type'] in ('audio', 'conversation_text') and not self.conversation_accepting):
            return
        if event['type'] == 'error':
            # Only our bounded numeric counters and allowlisted error codes;
            # never persist API messages, transcripts, or audio payloads.
            self.log('conversation_error', audioDiagnostics=self.conversation.diagnostics())
        if event['type'] == 'conversation_state':
            self.last_spoken_state = None
            self.conversation_announced = False
            if event['state'] == 'live':
                # A fresh voice session has no old-epoch audio awaiting ASR.
                self.voice_control_epoch = self.arbiter.epoch
                if self.conversation_interaction == 'chat_only' and self.conversation_accepting:
                    self.task(self.conversation.append('commentary',
                        'Greet the player briefly once in the configured language and invite them to talk. '
                        'This is conversation-only mode; no current Brain observations are available.'))
            if event['state'] not in ('live', 'mock') and self.arbiter.owner == 'gpt':
                await self.inhibit('conversation_disconnected')
            self.emit(self.state())
            self.log('conversation_state', state=event['state'],
                     audioDiagnostics=self.conversation.diagnostics())
        self.emit(event)

    async def voice_utterance(self, text, delegation_id, generation):
        if generation == self.conversation.context_generation:
            if self.conversation_interaction == 'chat_only':
                # Do not invoke Responses or construct an Action in this mode.
                if self.conversation_accepting:
                    await self.conversation.append('commentary',
                        'Conversation only. No action was executed. Current Brain observations are unavailable. '
                        'Continue the conversation; explain that body control is disabled if requested.', delegation_id)
                return
            try:
                self.start_intent(text, 'voice-' + str(uuid.uuid4()), self.arbiter.epoch, delegation_id)
            except ControlError as exc:
                self.emit({'type': 'error', 'error': str(exc)})

    def start_intent(self, text, command_id, epoch, delegation_id=None):
        if self.conversation_interaction == 'chat_only':
            raise ControlError('chat_only_cannot_control')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ControlError('invalid_text')
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 128:
            raise ControlError('invalid_command_id')
        if command_id in self.input_ids:
            raise ControlError('duplicate_command')
        if type(epoch) is not int or epoch != self.arbiter.epoch:
            raise ControlError('old_epoch')
        self.input_ids[command_id] = True
        if len(self.input_ids) > 4096:
            self.input_ids.popitem(last=False)
        self.intent_revision += 1
        for task in tuple(self.intent_tasks):
            task.cancel()
        self.task(self.player_intent(text, command_id, epoch, self.intent_revision, delegation_id), intent=True)

    async def player_intent(self, text, command_id, epoch, revision, delegation_id):
        started = time.monotonic()
        try:
            proposal = await self.conversation.interpret(text, self.summary(),
                self.config['control']['defaultActionMs'], self.config['control']['maxActionMs'])
            if epoch != self.arbiter.epoch or revision != self.intent_revision:
                raise ControlError('stale_intent')
            if (time.monotonic()-started)*1000 > self.config['control']['maxActionMs']:
                raise ControlError('expired_intent')
            if proposal['kind'] == 'action':
                if delegation_id is not None and self.voice_control_epoch != epoch:
                    raise ControlError('voice_session_restart_required')
                self.require_fresh()
                valid_ms = proposal['validForMs'] - (time.monotonic()-started)*1000
                self.arbiter.accept('gpt', proposal['action'], command_id, epoch, valid_ms)
                await self.submit(proposal['action'], 'gpt', command_id)
                reply = self.text('intent_sent')
            elif proposal['kind'] == 'question':
                reply = self.summary()['interpretation'] + ' ' + self.text('disclosure')
            else:
                reply = self.text('clarify')
            if self.conversation.mode == 'mock':
                self.emit({'type': 'conversation_text', 'role': 'assistant', 'text': '[MOCK] ' + reply, 'append': False})
            else:
                await self.conversation.append('commentary', reply, delegation_id)
        except asyncio.CancelledError:
            raise
        except (ControlError, ConversationError, BrainAdapterError) as exc:
            self.emit({'type': 'command_result', 'stage': 'rejected', 'commandId': command_id, 'reason': str(exc)})
            self.log('intent_rejected', commandId=command_id, reason=str(exc))
            if isinstance(exc, (ConversationError, BrainAdapterError)) and self.arbiter.owner == 'gpt':
                await self.inhibit('intent_service_failed')
            if epoch == self.arbiter.epoch:
                await self.conversation.append('commentary', self.text('rejected'), delegation_id)

    async def configure_conversation(self, event):
        request_id = event.get('requestId')
        try:
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                raise ControlError('invalid_settings_request_id')
            settings = validate_settings(event.get('settings'))
            async with self.conversation.lifecycle:
                if self.control_ws is None:
                    raise ControlError('control_client_required')
                if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
                    raise ControlError('old_epoch')
                if (type(event.get('expectedRevision')) is not int
                        or event['expectedRevision'] != self.conversation_settings_revision):
                    raise ControlError('stale_settings_revision')
                if request_id in self.settings_request_ids:
                    raise ControlError('duplicate_settings_request')
                if (self.conversation.state != 'off' or self.conversation.http is not None
                        or not self.arbiter.inhibited or self.switching or self.release_unknown):
                    raise ControlError('conversation_settings_require_stopped')
                # State changes are atomic (no await here). An old in-flight
                # interpretation cannot execute or describe the new settings.
                self.arbiter.inhibit('conversation_settings_changed')
                self.invalidate()
                self.conversation.settings = settings
                self.config['conversation'].update(settings)
                self.conversation_settings_revision += 1
                self.settings_request_ids[request_id] = True
                if len(self.settings_request_ids) > 256:
                    self.settings_request_ids.popitem(last=False)
                self.emit(self.state())
                self.emit({'type': 'conversation_settings', 'requestId': request_id,
                           'settings': dict(settings), 'revision': self.conversation_settings_revision,
                           'requiresExplicitStart': True})
                # Do not persist custom persona text in ordinary logs.
                self.log('conversation_settings_changed', revision=self.conversation_settings_revision,
                         language=settings['language'], voice=settings['voice'], persona=settings['persona'])
        except (ControlError, SettingsError) as exc:
            self.emit({'type': 'error', 'error': str(exc),
                       'requestId': request_id if isinstance(request_id, str) and len(request_id) <= 128 else None})

    async def command(self, event):
        if not isinstance(event, dict):
            raise ControlError('invalid_message')
        kind = event.get('type')
        if kind == 'configure_conversation':
            self.task(self.configure_conversation(event))
        elif kind == 'emergency_stop':
            await self.inhibit('emergency_stop')
        elif kind == 'set_owner':
            if self.conversation_interaction == 'chat_only' and event.get('owner') != 'observer':
                raise ControlError('chat_only_cannot_control')
            self.arbiter.set_owner(event.get('owner'))
            await self.inhibit('owner_changed')
        elif kind == 'resume':
            if self.conversation_interaction == 'chat_only':
                raise ControlError('chat_only_cannot_control')
            if self.arbiter.owner == 'observer':
                raise ControlError('observer_cannot_control')
            if self.arbiter.owner == 'gpt' and self.conversation.state not in ('live', 'mock'):
                raise ControlError('conversation_not_started')
            if not self.resume_ready():
                raise ControlError('fresh_stopped_brain_required')
            self.arbiter.resume()
            self.log('resumed')
            self.emit(self.state())
        elif kind == 'set_action':
            if self.conversation_interaction == 'chat_only':
                raise ControlError('chat_only_cannot_control')
            if self.motor_writer is not None:
                raise ControlError('manual_tcp_has_input_slot')
            self.require_fresh()
            self.arbiter.accept('manual', event.get('action'), event.get('commandId'),
                                event.get('controlEpoch'), event.get('validForMs'))
            await self.submit(event['action'], 'manual_ui', event['commandId'])
        elif kind == 'player_text':
            self.emit({'type': 'conversation_text', 'role': 'user', 'text': str(event.get('text', ''))[:2000], 'append': False})
            self.start_intent(event.get('text'), event.get('commandId'), event.get('controlEpoch'))
        elif kind == 'switch_target':
            if self.switching:
                raise ControlError('switch_in_progress')
            self.task(self.switch_target(event.get('profile')))
        elif kind == 'conversation_start':
            if self.closed:
                raise ControlError('bridge_closed')
            interaction = event.get('interaction', 'control')
            if interaction not in ('chat_only', 'control'):
                raise ControlError('invalid_conversation_interaction')
            if (self.conversation_operation is not None and not self.conversation_operation.done()
                    or self.conversation.state not in ('off', 'disconnected')):
                raise ControlError('conversation_already_started_or_stopping')
            if interaction == 'chat_only':
                if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
                    raise ControlError('old_epoch')
                self.arbiter.set_owner('observer')
                await self.inhibit('chat_only')
            self.conversation_interaction = interaction
            self.conversation.interaction = interaction
            self.conversation_generation += 1
            self.conversation_accepting = True
            self.emit(self.state())
            self.conversation_operation = self.task(self.conversation.start())
        elif kind == 'conversation_stop':
            if self.arbiter.owner == 'gpt':
                await self.inhibit('conversation_stopped')
            self.stop_conversation_session()
        elif kind == 'audio':
            if self.conversation_interaction == 'chat_only':
                if (not self.conversation_accepting or type(event.get('conversationGeneration')) is not int
                        or event['conversationGeneration'] != self.conversation_generation):
                    raise ControlError('old_conversation_generation')
            elif event.get('controlEpoch') != self.arbiter.epoch:
                raise ControlError('old_audio_epoch')
            await self.conversation.input_audio(event.get('audio'))
        else:
            raise ControlError('unknown_message')

    def stop_conversation_session(self):
        # Reserve the lifecycle operation synchronously: queued starts cannot
        # resurrect a session after Stop / WS disconnect / identity replacement.
        self.conversation_accepting = False
        self.conversation_generation += 1
        self.conversation.clear_context()
        self.emit({'type': 'discard_audio', 'epoch': self.arbiter.epoch})
        self.emit(self.state())
        previous = self.conversation_operation
        if previous is not None and not previous.done():
            previous.cancel()
        async def stop():
            if previous is not None:
                await asyncio.gather(previous, return_exceptions=True)
            await self.conversation.stop()
        self.conversation_operation = self.task(stop())

    async def watchdog(self):
        while True:
            await asyncio.sleep(.1)
            if not self.arbiter.inhibited:
                if self.arbiter.expired():
                    self.log('command_expired')
                    await self.inhibit('command_expired')
                elif self.summary()['stale']:
                    await self.inhibit('stale_brain')
            self.emit(self.state())
            if time.monotonic()-self.last_summary > 2:
                self.last_summary = time.monotonic()
                summary = self.summary()
                self.emit({'type': 'brain_summary', 'summary': summary})
                if self.conversation_interaction == 'chat_only':
                    continue  # General voice remains valid without fresh Brain data.
                semantic = (summary['stale'], summary['interpretation'], self.arbiter.inhibited)
                if semantic != self.last_spoken_state:
                    self.last_spoken_state = semantic
                    context = json.dumps({'observation': summary['interpretation'],
                        'stale': summary['stale'], 'outputInhibited': self.arbiter.inhibited,
                        'bodyMovementVerified': False}, ensure_ascii=False)
                    # Changes of *observed* state drive character speech; no
                    # speech is generated just because an action was requested.
                    channel = 'commentary' if self.conversation_announced else 'thinking'
                    self.conversation_announced = self.conversation.state in ('live', 'mock')
                    self.task(self.conversation.append(channel, context))

    def check_origin(self, request):
        port = self.config['bridge']['controlPort']
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
        if request.host not in hosts:
            raise web.HTTPForbidden(text='invalid_host')
        origin = request.headers.get('Origin')
        if origin is not None and origin not in {'http://' + host for host in hosts}:
            raise web.HTTPForbidden(text='invalid_origin')

    async def page(self, request):
        self.check_origin(request)
        return web.Response(text=Path(__file__).with_name('player.html').read_text(encoding='utf-8'),
                            content_type='text/html', headers={'Cache-Control': 'no-store',
                            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'})

    async def player_page(self, request):
        """Serve the separately owned browser UI on the control WS origin.

        No directory listings, build scripts, notes, secret files, symlink
        escapes, arbitrary filesystem paths, or cross-origin API access.
        """
        self.check_origin(request)
        if request.path == '/player':
            raise web.HTTPFound('/player/')
        runtime = Path(__file__).resolve().parents[1]
        root = (runtime / 'Player').resolve()
        path = (root / (request.match_info.get('asset') or 'index.html')).resolve()
        if (not root.is_relative_to(runtime) or not path.is_relative_to(root)
                or path.suffix.lower() not in {'.html', '.js', '.css', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.woff2'}
                or not path.is_file()):
            raise web.HTTPNotFound(text='player_asset_not_found')
        return web.FileResponse(path, headers={'Cache-Control': 'no-store',
            'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})

    async def websocket(self, request):
        self.check_origin(request)
        if self.control_ws is not None:
            raise web.HTTPConflict(text='control_client_already_connected')
        # Keep loopback control/audio frames uncompressed. The embedded browser
        # / aiohttp deflate path produced RSV errors on the first command.
        # Disable negotiation, never weaken the frame parser's validation.
        ws = web.WebSocketResponse(max_msg_size=128*1024, heartbeat=10, compress=False)
        # Reserve before the first await, including the HTTP upgrade.
        self.control_ws = ws
        queue = asyncio.Queue(maxsize=128)
        self.control_queue = queue
        sender = None
        try:
            await ws.prepare(request)
            self.log('control_client_connected', compression=ws.compress)
            async def send():
                while True:
                    await asyncio.wait_for(ws.send_json(await queue.get()), timeout=2)
            sender = self.task(send())
            self.emit(self.state())
            self.emit(options_message())
            if self.frame:
                self.emit(self.frame)
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        await self.command(json.loads(message.data))
                    except (ValueError, TypeError, KeyError, BrainAdapterError, ConversationError) as exc:
                        self.emit({'type': 'error', 'error': str(exc) if isinstance(exc, (ControlError, ConversationError, BrainAdapterError)) else 'invalid_message'})
                elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    if message.type == WSMsgType.ERROR:
                        error = message.data
                        # Classify parser errors without logging payloads,
                        # transcripts, or custom persona text from the wire.
                        description = str(error)
                        category = 'transport_error'
                        for phrase, label in (
                            ('reserved bits', 'reserved_bits'),
                            ('Continuation frame', 'unexpected_continuation'),
                            ('opcode', 'invalid_opcode'),
                            ('fragmented control frame', 'fragmented_control'),
                            ('Control frame payload', 'control_too_large'),
                            ('Invalid close', 'invalid_close'),
                            ('UTF-8', 'invalid_utf8'),
                            ('exceeds', 'message_too_large'),
                        ):
                            if phrase in description:
                                category = label
                                break
                        code = getattr(error, 'code', None)
                        self.log('control_ws_error', error=type(error).__name__,
                                 category=category, code=int(code) if isinstance(code, int) else None,
                                 compression=ws.compress)
                    break
        finally:
            self.log('control_client_closed', closeCode=ws.close_code)
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            if self.control_ws is ws:
                self.control_ws = self.control_queue = None
                if not self.closed:
                    await self.inhibit('control_client_disconnected')
                    self.stop_conversation_session()
        return ws

    async def motor_client(self, reader, writer):
        if self.motor_writer is not None or self.control_ws is None or self.arbiter.inhibited:
            writer.write(b'{"type":"error","error":"bridge_control_required_or_inhibited"}\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return
        self.motor_writer = writer
        self.unity_generation += 1
        generation = self.unity_generation
        queue = asyncio.Queue(maxsize=16)
        self.motor_queue = queue
        async def send():
            try:
                while True:
                    event = await queue.get()
                    writer.write(json.dumps(event, allow_nan=False).encode() + b'\n')
                    await asyncio.wait_for(writer.drain(), timeout=1)
            finally:
                writer.close()
        sender = self.task(send())
        self.motor_emit(self.adapter.status)
        try:
            while line := await reader.readline():
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get('type') != 'set_action':
                        raise ControlError('expected_set_action')
                    rid = event.get('requestId')
                    if type(rid) is not int or rid <= 0:
                        raise ControlError('positive_request_id_required')
                    command_id = f'unity-{generation}-{rid}'
                    self.require_fresh()
                    self.arbiter.accept('manual', event.get('action'), command_id,
                                        self.arbiter.epoch, self.config['control']['defaultActionMs'])
                    await self.submit(event['action'], 'manual_tcp', command_id, rid)
                except (ValueError, TypeError, KeyError, BrainAdapterError):
                    self.motor_emit({'type': 'error', 'error': 'command_rejected'})
        except (ConnectionError, ValueError):
            pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            if self.motor_writer is writer:
                self.motor_writer = self.motor_queue = None
                if not self.closed and not self.arbiter.inhibited:
                    await self.inhibit('motor_client_disconnected')
            writer.close()
            await writer.wait_closed()

    async def start(self):
        path = Path(self.config['logPath'])
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=32*1024*1024, backupCount=2, encoding='utf-8')
        self.log_file = logging.getLogger('flylingual.bridge.' + str(uuid.uuid4()))
        self.log_file.setLevel(logging.INFO)
        self.log_file.propagate = False
        self.log_file.addHandler(handler)
        self.log('bridge_started', profile=self.profile, conversationMode=self.conversation.mode)
        try:
            await self.connect_brain(self.target)
        except Exception as exc:
            self.arbiter.reason = 'brain_connect_failed'
            self.log('brain_connect_failed', error=type(exc).__name__)
        self.task(self.watchdog())

    async def close(self):
        self.closed = True
        self.stop_conversation_session()
        await self.inhibit('bridge_shutdown')
        await self.conversation_operation
        if self.adapter and self.adapter.connected:
            try:
                self.log('controller_released', **await self.adapter.release())
            except Exception:
                self.log('release_unknown')
        if self.adapter:
            await self.adapter.close()
        if self.control_ws is not None:
            await self.control_ws.close()
        for task in tuple(self.tasks | self.intent_tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks | self.intent_tasks), return_exceptions=True)
        self.log('bridge_stopped')
        if self.log_file:
            for handler in self.log_file.handlers[:]:
                handler.close()
                self.log_file.removeHandler(handler)
            self.log_file = None


async def run(config):
    bridge = Bridge(config)
    app = web.Application(client_max_size=128*1024)
    app.router.add_get('/', bridge.page)
    app.router.add_get('/ws', bridge.websocket)
    app.router.add_get('/player', bridge.player_page)
    app.router.add_get('/player/', bridge.player_page)
    app.router.add_get('/player/{asset:.*}', bridge.player_page)
    runner = web.AppRunner(app, access_log=None)
    tcp = None
    shutdown_watcher = None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows asyncio.run handles keyboard interrupt.
    try:
        await runner.setup()
        await web.TCPSite(runner, config['bridge']['host'], config['bridge']['controlPort']).start()
        tcp = await asyncio.start_server(bridge.motor_client, config['bridge']['host'],
                                        config['bridge']['tcpPort'], limit=65536)
        await bridge.start()
        if config.get('_shutdownFile'):
            async def watch_shutdown():
                while not Path(config['_shutdownFile']).exists():
                    await asyncio.sleep(.2)
                stopped.set()
            shutdown_watcher = asyncio.create_task(watch_shutdown())
        print(f"BRIDGE READY http://{config['bridge']['host']}:{config['bridge']['controlPort']} ready=false", flush=True)
        await stopped.wait()
    finally:
        if shutdown_watcher:
            shutdown_watcher.cancel()
            await asyncio.gather(shutdown_watcher, return_exceptions=True)
        if tcp:
            tcp.close()
            await tcp.wait_closed()
        await bridge.close()
        await runner.cleanup()
