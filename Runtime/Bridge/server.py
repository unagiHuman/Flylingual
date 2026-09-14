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
from .action_plans import (BoundedPlanRunner, LocalSafetyObservation, PLAN_REPLY, PLAN_STEPS,
                           DISTANCE_ACTIONS, valid_distance, validate_intent)
from .blind_run_script import BlindRunScript
from .local_visual_observation import LocalVisualObservation
from .config import load_config
from .control import ControlArbiter, ControlError
from .conversation import ConversationAdapter, ConversationError
from .conversation_settings import SettingsError, options_message, validate_settings
from .translation import message_text, summarize
from .neural_response import NeuralResponseAnalyzer, number
from .neural_feedback import NeuralFeedbackScheduler, compact_summary, SPONTANEOUS
from .environment_feedback import EnvironmentFeedback
from .visual_threat_feedback import VisualThreatFeedbackMixin


VOICE_TEST_EVENTS = frozenset({
    'voice_intent_dispatch', 'intent_classified', 'intent_rejected',
    'command_submitted', 'command_applied', 'command_accepted', 'command_superseded',
    'command_expired', 'output_inhibited', 'plan_started', 'plan_step_submitted',
    'plan_stopped', 'local_observation_received', 'audio_fixture_sent', 'delegation_observed',
    'execution_updated', 'execution_started', 'execution_ended',
    'input_transcript_observed', 'transcript_candidate_observed', 'transcript_candidate_result',
    'context_append_observed', 'player_speech_interrupt',
    'intent_classification_started',
})
VOICE_TEST_FIELDS = frozenset({
    'commandId', 'requestId', 'sequence', 'action', 'source', 'kind', 'plan',
    'planId', 'name', 'step', 'outcome', 'reason', 'proposalValidForMs',
    'interpretationMs', 'continuedListening', 'e2eMs', 'accepted',
    'fixtureId', 'fixtureChunkIndex', 'audioStartMs', 'audioEndMs',
    'delegationId', 'inputId', 'startMs', 'endMs', 'offsetMs',
    'intentAgeMs', 'executionDurationMs',
    'transcriptChars',
    'executionId', 'executionMode', 'operation', 'targetExecutionId', 'monitorHazards',
    'targetDistanceMeters', 'traveledMeters', 'remainingMeters', 'completed',
    'distancePhase', 'stopRequestId', 'stopTrigger',
    'interpretRoute', 'utteranceFinalized', 'speechEndMs', 'speechEndMonotonicMs',
})


def command_error_message(exc, event, current_epoch):
    """Bounded correlation for stale requests; never echo command payloads."""
    code = str(exc) if isinstance(exc, (ControlError, ConversationError, BrainAdapterError)) else 'invalid_message'
    result = {'type': 'error', 'error': code}
    if code == 'old_epoch' and isinstance(event, dict):
        kind, submitted = event.get('type'), event.get('controlEpoch')
        if (kind in ('local_safety_observation', 'local_visual_observation', 'blind_run_cue', 'resume', 'conversation_start',
                     'set_action', 'player_text', 'configure_conversation')
                and type(submitted) is int and type(current_epoch) is int
                and 0 <= submitted <= 2**31 - 1 and 0 <= current_epoch <= 2**31 - 1):
            result.update(requestType=kind, submittedEpoch=submitted, currentEpoch=current_epoch,
                          hasEpochContext=True)
    return result


class Bridge(VisualThreatFeedbackMixin):
    def __init__(self, config):
        self.config = config
        self.arbiter = ControlArbiter(config['control'])
        self.adapter = None
        self.target = config['brain']
        self.profile = config['profile']
        self.conversation = ConversationAdapter(config['conversation'], self.conversation_event,
                                                self.voice_utterance, self.transcript_utterance)
        self.blind_script = BlindRunScript()
        self.environment = EnvironmentFeedback(config['control']['staleMs'])
        self.environment_generation = None
        self.environment_sender = None
        self.init_visual_threat()
        self.local_observation = LocalSafetyObservation()
        self.local_visual = LocalVisualObservation()
        self.local_visual_commentary_count = 0
        self.edge_warning_scope = None
        self.edge_warning_sent = False
        self.plans = BoundedPlanRunner(self)
        self.active_execution = None
        self.last_execution_context = None
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
        self.native_voice_control = False
        self.conversation_generation = 0
        self.conversation_accepting = False
        self.conversation_operation = None
        self.brain_identity = None
        self.closed = False
        self.log_file = None
        self.voice_test_observation = False
        feedback = config.get('neuralFeedback', {})
        self.neural = NeuralResponseAnalyzer({**feedback, 'staleMs': config['control']['staleMs']})
        self.conversation.neural_feedback_enabled = self.neural.enabled
        self.neural_scheduler = NeuralFeedbackScheduler(feedback)
        self.neural_subscribed = False
        self.neural_body = None
        self.neural_sender = None
        self.neural_output_at = -1e15
        self.player_priority_until = -1e15
        self.player_transcript_at = -1e15
        self.neural_last_hud = None
        self.neural_last_context = None
        self.neural_context_appends = 0
        self.neural_max_chars = 0

    def clear_neural(self):
        self.clear_visual_threat_history()
        self.cancel_visual_threat()
        self.environment.clear_current()
        if self.environment_sender is not None and not self.environment_sender.done():
            self.environment_sender.cancel()
        self.neural.reset()
        self.neural_scheduler.reset()
        self.neural_body = None
        self.neural_last_context = self.neural_last_hud = None
        if self.neural_sender is not None and not self.neural_sender.done():
            self.neural_sender.cancel()

    def neural_snapshot(self):
        body = self.neural_body
        now = time.monotonic() * 1000
        if body is not None:
            body = {**body, 'ageMs': body['initialAgeMs'] + now - body['receivedMonotonicMs']}
        return self.neural.snapshot(now, self.age_ms(), self.arbiter.epoch,
                                    self.conversation_generation, body=body)

    def observe_neural(self, frame):
        if not self.neural.enabled:
            return
        started = time.monotonic() * 1000
        analysis_started = time.perf_counter()
        item = self.requests.get(self.request_counter)
        request = ({'requestId': self.request_counter, 'action': item['action'],
                    'sentMonotonicMs': item['sent'] * 1000}
                   if item and item['epoch'] == self.arbiter.epoch else None)
        event = self.neural.observe(frame, identity=self.adapter.status if self.adapter else {},
            epoch=self.arbiter.epoch, generation=self.conversation_generation,
            received_ms=started, age_ms=self.age_ms(), request=request, inhibited=self.arbiter.inhibited)
        if event:
            self.neural_scheduler.offer(event)
        self.log('neural_observation', sequence=frame.get('sequence'),
                 eventType=event.get('eventType') if event else None,
                 analysisMs=(time.perf_counter()-analysis_started)*1000, bufferedFrames=self.neural.buffered_frames)

    def accept_neural_body(self, event):
        required = {'type', 'controlEpoch', 'conversationGeneration', 'sequence', 'ageMs',
                    'brainSequence', 'brainSessionId', 'brainInstanceId'}
        optional = {'horizontalSpeedMetersPerSecond', 'forwardSpeedMetersPerSecond',
                    'yawRateDegreesPerSecond', 'travelMeters', 'unityMonotonicMs'}
        if (not required <= set(event) or set(event) - required - optional
                or any(type(event[k]) is not int or event[k] < 0 for k in
                       ('controlEpoch', 'conversationGeneration', 'sequence', 'brainSequence'))
                or any(number(event[k]) is None for k in ('ageMs',) + tuple(optional & set(event)))
                or any(type(event[k]) is not str or not 0 < len(event[k]) <= 256 for k in ('brainSessionId', 'brainInstanceId'))
                or any(event[k] < 0 for k in ('horizontalSpeedMetersPerSecond', 'travelMeters', 'unityMonotonicMs') if k in event)
                or not 0 <= event['ageMs'] <= self.config['control']['staleMs']):
            raise ControlError('invalid_body_response_observation')
        if not self.neural.enabled or not self.neural_subscribed:
            return
        status = self.adapter.status if self.adapter else {}
        if (event['controlEpoch'] != self.arbiter.epoch
                or event['conversationGeneration'] != self.conversation_generation
                or event['brainSessionId'] != status.get('sessionId')
                or event['brainInstanceId'] != status.get('instanceId')):
            return  # Queued old observations are never gameplay errors.
        previous = self.neural_body
        if previous and event['sequence'] <= previous['sequence']:
            return
        self.neural_body = {'source': 'unity', 'fresh': True,
            'sequence': event['sequence'], 'brainSequence': event['brainSequence'],
            'sessionId': event['brainSessionId'], 'instanceId': event['brainInstanceId'],
            'controlEpoch': event['controlEpoch'], 'conversationGeneration': event['conversationGeneration'],
            'ageMs': event['ageMs'], 'initialAgeMs': event['ageMs'], 'receivedMonotonicMs': time.monotonic()*1000,
            'horizontalSpeed': event.get('horizontalSpeedMetersPerSecond'),
            'forwardSpeed': event.get('forwardSpeedMetersPerSecond'),
            'yawRateDegPerSec': event.get('yawRateDegreesPerSecond'),
            'travelMeters': event.get('travelMeters'), 'unityMonotonicMs': event.get('unityMonotonicMs')}

    async def send_neural_context(self, channel, event):
        # A single consumer. Validate again immediately before the only API await.
        current = self.neural_snapshot()
        if (not current or not current.get('fresh') or self.arbiter.inhibited
                or self.conversation_interaction != 'control' or not self.conversation_accepting
                or self.conversation.state != 'live'
                or current.get('controlEpoch') != event.get('controlEpoch')
                or current.get('conversationGeneration') != event.get('conversationGeneration')
                or current.get('identity') != event.get('identity')
                or (event.get('current') or {}).get('requestedRequestId') != self.request_counter
                or (current.get('current') or {}).get('requestedRequestId') != self.request_counter
                or (channel == 'commentary' and (self.player_has_priority() or current.get('eventType') not in SPONTANEOUS
                    or current.get('eventType') != event.get('eventType')
                    or current.get('allowedClaims') != event.get('allowedClaims')
                    or time.monotonic()-self.conversation.last_voice_end_at < 1
                    or time.monotonic()*1000-self.neural_output_at < 1500 or bool(self.intent_tasks)))
                or time.monotonic()*1000 < self.neural_scheduler.blocked_until_ms):
            return
        content = compact_summary(current, self.conversation.settings['language'],
                                  no_sarcasm=self.neural_scheduler.no_sarcasm)
        self.log('neural_context_append', eventId=current['eventId'], channel=channel, chars=len(content))
        self.neural_context_appends += 1
        self.neural_max_chars = max(self.neural_max_chars, len(content))
        await self.conversation.append(channel, content)

    def publish_neural(self):
        if not self.neural.enabled:
            return
        event = self.neural_snapshot()
        if not event:
            return
        # Nonessential HUD traffic cannot fill the control queue or close it.
        if self.neural_subscribed and self.control_queue is not None and self.control_queue.qsize() < 96:
            self.control_queue.put_nowait({'type': 'neural_response', **event})
        if self.neural_sender is not None and not self.neural_sender.done():
            return
        # Body measurements arrive after their Brain frame; refresh the one
        # pending event with the correlated snapshot before presentation.
        self.neural_scheduler.offer(event)
        now = time.monotonic()*1000
        busy = (self.player_has_priority() or now - self.conversation.last_voice_end_at*1000 < 1000
                or now - self.neural_output_at < 1500 or bool(self.intent_tasks))
        selected, reason = self.neural_scheduler.take(now, epoch=self.arbiter.epoch,
            generation=self.conversation_generation, request_id=self.request_counter,
            session_id=(event.get('identity') or {}).get('sessionId'), inhibited=self.arbiter.inhibited,
            chat_only=self.conversation_interaction == 'chat_only', busy=busy)
        if selected:
            self.neural_sender = self.task(self.send_neural_context('commentary', selected))
        elif not busy and now >= self.neural_scheduler.blocked_until_ms:
            # One factual thinking update per applied request, without unsolicited speech.
            current = event.get('current') or {}
            key = (event.get('controlEpoch'), event.get('conversationGeneration'), current.get('appliedRequestId'), event.get('fresh'))
            if key != self.neural_last_context and current.get('stimulusApplied') and event.get('fresh'):
                self.neural_last_context = key
                self.neural_sender = self.task(self.send_neural_context('thinking', event))

    def neural_user_input(self, text):
        self.neural_scheduler.interrupt(time.monotonic()*1000)
        self.neural_scheduler.preference(text)
        self.player_priority_until = time.monotonic() + 6

    def player_speech_started(self):
        if not self.conversation_accepting:
            return
        self.player_priority_until = time.monotonic() + 6
        self.neural_scheduler.interrupt(time.monotonic()*1000, 6000)
        self.emit({'type': 'discard_audio', 'epoch': self.arbiter.epoch})
        self.log('player_speech_interrupt')

    def player_has_priority(self):
        now = time.monotonic()
        return (now < self.player_priority_until
                or now - self.conversation.last_voice_end_at < 1
                or bool(self.intent_tasks)
                or (self.player_priority_until > 0 and now*1000 - self.neural_output_at < 1500))

    async def speak_non_action(self, context, delegation_id=None):
        if self.neural.enabled:
            # Commentary is paraphrased as speech; factual context belongs in
            # thinking, followed by a short behavioral redirect for questions.
            self.neural_context_appends += 1
            self.neural_max_chars = max(self.neural_max_chars, len(context))
            self.log('neural_question_context', chars=len(context))
            await self.conversation.append('thinking', context, delegation_id)
            instruction = ('最新のプレイヤーの質問・雑談に直接答えて。台本の続きや移動の催促に置き換えず、'
                           '事実と未確認を区別して短い1〜2文で。一般質問にはその話題で答えて。'
                           if self.conversation.settings['language'] == 'ja' else
                           'Answer the latest player question or chat directly in one or two short sentences. '
                           'Do not continue tutorial lines or ask them to move. Preserve unknowns. Answer general topics normally. ')
            if self.neural_scheduler.no_sarcasm:
                instruction += '皮肉なし。' if self.conversation.settings['language'] == 'ja' else 'No sarcasm. '
            await self.conversation.append('instructions', instruction)
        else:
            await self.conversation.append('commentary', context, delegation_id)

    def log(self, event, **fields):
        stamp = round(time.monotonic()*1000, 3)
        if self.log_file:
            self.log_file.info(json.dumps({'event': event, 'monotonicMs': stamp,
                                            'epoch': self.arbiter.epoch, **fields},
                                           ensure_ascii=False, allow_nan=False))
        if self.voice_test_observation and event in VOICE_TEST_EVENTS:
            self.emit({'type': 'voice_test_diagnostic', 'event': event,
                       'monotonicMs': stamp, 'epoch': self.arbiter.epoch,
                       'conversationGeneration': self.conversation_generation,
                       **{k: v for k, v in fields.items() if k in VOICE_TEST_FIELDS}})

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

    def intent_context(self):
        # Only a current, still-running GPT command can ground "a little more".
        # Never use assistant speech, a past target, or motor signs as an order.
        active = None
        execution = self.current_execution()
        if execution is not None and not self.summary()['stale']:
            item = self.requests.get(execution['requestId'], {})
            active = {k: execution[k] for k in ('executionId', 'action', 'plan', 'step',
                      'executionMode', 'monitorHazards')}
            active['brainApplied'] = item.get('applied', False)
            active['remainingMs'] = (None if execution['deadline'] is None else
                                     max(0, int((execution['deadline'] - time.monotonic()) * 1000)))
            active.update(self.distance_summary(execution))
            if execution.get('distancePhase'):
                active['distancePhase'] = execution['distancePhase']
                active['stopApplied'] = bool(self.requests.get(execution.get('stopRequestId'), {}).get('applied'))
        return {**self.summary(), 'localSafety': self.local_observation.summary(),
                'localVisual': self.local_visual.summary(),
                'activeCommand': active}

    def current_execution(self):
        execution = self.active_execution
        if (execution is None or self.arbiter.inhibited or self.arbiter.owner != 'gpt'
                or execution['epoch'] != self.arbiter.epoch
                or execution['generation'] != self.conversation_generation
                or (execution['deadline'] is not None and time.monotonic() >= execution['deadline'])):
            return None
        item = self.requests.get(execution['requestId'], {})
        if item.get('rejected') or item.get('superseded'):
            return None
        return execution

    @staticmethod
    def distance_summary(execution):
        return {k: execution.get(k) for k in ('targetDistanceMeters', 'traveledMeters', 'remainingMeters')}

    def distance_state(self, distance, action, plan, *, updating=False):
        if (not valid_distance(distance) or plan in ('nudge_right', 'nudge_left')
                or (plan is None and action not in DISTANCE_ACTIONS)):
            raise ControlError('invalid_distance_execution')
        travel = self.local_observation.require_distance()
        now = time.monotonic()
        # A new turn-then-forward plan acquires its origin only at forward
        # phase entry. An explicit distance update means "from here".
        origin = travel if updating or action in DISTANCE_ACTIONS else None
        return {'targetDistanceMeters': float(distance), 'originTravelMeters': origin,
                'traveledMeters': 0.0, 'remainingMeters': float(distance),
                'distanceStartedAt': now, 'lastProgressAt': now, 'progressTravelMeters': 0.0,
                'distanceApplied': False, 'distanceSequence': self.local_observation.sequence,
                'distancePhase': 'moving', 'stopRequestId': None, 'stopSentAt': None,
                'settledSince': None, 'settledTravelMeters': None, 'stopTrigger': None}

    def activate_execution(self, command_id, action, execution_mode, deadline, *,
                           plan=None, monitor_hazards=False, target_distance_meters=None):
        distance = (self.distance_state(target_distance_meters, action, plan)
                    if execution_mode == 'distance' else {})
        monitor_hazards |= execution_mode == 'distance'
        self.arbiter.deadline = deadline
        self.active_execution = {'executionId': command_id, 'action': action, 'plan': plan,
                                 'step': 0, 'executionMode': execution_mode, 'deadline': deadline,
                                 'monitorHazards': monitor_hazards, 'requestId': None,
                                 'epoch': self.arbiter.epoch, 'generation': self.conversation_generation,
                                 'startedAt': time.monotonic(), **distance}
        self.log('execution_started', executionId=command_id, action=action, plan=plan,
                 executionMode=execution_mode, monitorHazards=monitor_hazards,
                 **self.distance_summary(self.active_execution))

    def update_execution_step(self, execution_id, action, step):
        execution = self.current_execution()
        if execution is None or execution['executionId'] != execution_id:
            raise ControlError('stale_execution')
        if execution['executionMode'] == 'distance' and action in DISTANCE_ACTIONS:
            travel = self.local_observation.require_distance()
            if execution['originTravelMeters'] is None:
                execution['originTravelMeters'] = travel
                execution['lastProgressAt'] = time.monotonic()
        execution.update(action=action, step=step, requestId=None)

    def clear_execution(self, reason):
        execution = self.active_execution
        self.active_execution = None
        if execution:
            self.log('execution_ended', executionId=execution['executionId'], reason=reason,
                     **self.distance_summary(execution))

    def update_execution(self, proposal, command_id, epoch):
        # No await: validation, deduplication and the in-place update are atomic
        # relative to STOP, expiry and phase transitions on this event loop.
        self.require_fresh()
        execution = self.current_execution()
        if execution is None or execution['executionId'] != proposal['targetExecutionId']:
            raise ControlError('stale_execution')
        if execution['executionMode'] == 'distance':
            self.local_observation.require_distance()
            if self.local_observation.travel_fault_sequence > execution['distanceSequence']:
                raise ControlError(self.local_observation.travel_fault_reason)
        operation = proposal['operation']
        mode = proposal['executionMode']
        restarting = (execution.get('distancePhase') == 'braking'
                      and mode in ('distance', 'timed', 'until_next_command'))
        deadline = execution['deadline']
        distance_update = None
        if mode == 'inherit':
            mode = execution['executionMode']
        elif mode == 'until_next_command':
            if execution['plan'] in ('nudge_right', 'nudge_left'):
                raise ControlError('cannot_extend_nudge')
            deadline = None
        elif mode == 'timed':
            deadline = time.monotonic() + proposal['validForMs'] / 1000
        elif mode == 'distance':
            distance_update = self.distance_state(proposal.get('distanceMeters'), execution['action'],
                                                  execution['plan'], updating=True)
            deadline = None
        monitoring = execution['monitorHazards'] or operation == 'modify_conditions' or mode == 'distance'
        if monitoring:
            concern = self.local_observation.concern(action=execution['action'])
            if concern:
                raise ControlError(concern)
        duration = None if deadline is None else (deadline - time.monotonic()) * 1000
        self.arbiter.accept('gpt', execution['action'], command_id, epoch, duration,
                            execution_mode=mode)
        self.arbiter.deadline = deadline
        if restarting:
            # A STOP transport callback can still be awaiting. A new object,
            # even under the same logical ID, makes its exact-object guard fail.
            execution = dict(execution)
            execution.update(requestId=None, distancePhase=None, stopRequestId=None, stopSentAt=None,
                             settledSince=None, settledTravelMeters=None, stopTrigger=None)
            self.active_execution = execution
        execution.update(executionMode=mode, deadline=deadline, monitorHazards=monitoring)
        if distance_update is not None:
            execution.update(distance_update)
        elif mode != 'distance':
            execution.update(targetDistanceMeters=None, traveledMeters=None, remainingMeters=None,
                             distancePhase=None)
        if self.plans.active is not None:
            self.plans.active.update(deadline=deadline, executionMode=mode)
        self.log('execution_updated', executionId=execution['executionId'], commandId=command_id,
                 action=execution['action'], plan=execution['plan'], step=execution['step'],
                 operation=operation, executionMode=mode, monitorHazards=monitoring,
                 **self.distance_summary(execution))
        self.emit({'type': 'command_result', 'stage': 'execution_updated', 'commandId': command_id,
                   'executionId': execution['executionId'], 'action': execution['action'],
                   'epoch': epoch, 'message': self.text('intent_sent')})
        self.emit(self.state())
        return execution if restarting else None

    def text(self, key):
        return message_text(key, self.conversation.settings['language'])

    def execution_state(self):
        execution = self.current_execution()
        if execution is None:
            return None
        state = {k: execution[k] for k in ('executionId', 'action', 'plan', 'step',
                 'executionMode', 'monitorHazards', 'requestId')}
        state['remainingMs'] = (None if execution['deadline'] is None else
                                max(0, (execution['deadline'] - time.monotonic()) * 1000))
        state.update(self.distance_summary(execution))
        state['distancePhase'] = execution.get('distancePhase')
        return state

    def publish_execution_context(self):
        # Live must know which request is being held, but remains an observer:
        # only a new player utterance can cause a client delegation/update.
        if (self.conversation_interaction != 'control' or not self.conversation_accepting
                or self.conversation.state != 'live'):
            return
        execution = self.current_execution()
        context = ({k: execution[k] for k in ('executionId', 'action', 'plan', 'step',
                    'executionMode', 'monitorHazards')} if execution else None)
        if context is not None:
            context['brainApplied'] = bool(self.requests.get(execution['requestId'], {}).get('applied'))
            if execution.get('distancePhase'):
                context['distancePhase'] = execution['distancePhase']
        if context == self.last_execution_context:
            return
        self.last_execution_context = context
        # IDs stay in the backend. Omit the changing remaining time to avoid
        # periodic re-injection and keep the complete notice below 380 chars.
        visible = ({k: v for k, v in context.items() if k != 'executionId'} if context else None)
        content = ('Backend state, not proof of movement. Not a command. '
                   'brainApplied=true completes stimulus application; backend holds execution. '
                   'Ready for new player requests including "そのまま". '
                   + json.dumps({'activeRequest': visible}, ensure_ascii=False, separators=(',', ':')))
        self.task(self.conversation.append('thinking', content))

    def state(self):
        status = self.adapter.status if self.adapter else {}
        return {'type': 'bridge_state', 'epoch': self.arbiter.epoch,
                'owner': self.arbiter.owner, 'outputInhibited': self.arbiter.inhibited,
                'reason': self.arbiter.reason, 'profile': self.profile,
                'target': {'host': self.target['host'], 'port': self.target['port']},
                'brainConnected': bool(self.adapter and self.adapter.connected), 'brainReady': False,
                'conversationState': self.conversation.state, 'conversationMode': self.conversation.mode,
                'capabilities': ['conversation_only_v1', 'native_voice_actions_v1', 'blind_run_script_v1', 'environment_feedback_v1', 'local_visual_observation_v1', 'bounded_action_plans_v1', 'persistent_intents_v1', 'distance_intents_v1'] + (['neural_response_v1'] if self.neural.enabled else []),
                'activeExecution': self.execution_state(),
                'actionPlan': ({k: self.plans.active[k] for k in ('planId', 'name', 'step', 'requestId')}
                               if self.plans.active else None),
                'localSafety': self.local_observation.summary(),
                'conversationInteraction': self.conversation_interaction,
                'conversationGeneration': self.conversation_generation,
                'conversationStopping': bool(self.conversation_operation and not self.conversation_operation.done()),
                'motorEndpoint': {'host': self.config['bridge']['host'], 'port': self.config['bridge']['tcpPort']},
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
        self.clear_neural()
        self.clear_execution('invalidated')
        self.last_execution_context = None
        self.plans.cancel()
        self.local_observation.clear()
        self.local_visual.clear()
        self.blind_script.last_fact = None
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

    async def submit(self, action, source, command_id, unity_id=None, *,
                     intent_age_ms=None, execution_duration_ms=None, delegation_id=None, notify_live=False,
                     preserve_execution=None):
        if self.conversation_interaction == 'chat_only' and source != 'safety':
            raise ControlError('chat_only_cannot_control')
        if not self.adapter or not self.adapter.connected:
            raise ControlError('brain_disconnected')
        if preserve_execution is not None and (action != 'STOP'
                or self.active_execution is not preserve_execution
                or preserve_execution.get('distancePhase') != 'braking'):
            raise ControlError('stale_execution')
        self.request_counter += 1
        request_id = self.request_counter
        item = {'source': source, 'commandId': command_id, 'action': action,
                'epoch': self.arbiter.epoch, 'unityId': unity_id,
                'unityGeneration': self.unity_generation, 'sent': time.monotonic(), 'applied': False,
                'delegationId': delegation_id, 'notifyLive': notify_live, 'conversationGeneration': self.conversation_generation,
                'contextGeneration': self.conversation.context_generation, 'applicationNoticeSent': False}
        self.requests[request_id] = item
        while len(self.requests) > 4096:
            self.requests.popitem(last=False)
        if action == 'STOP':
            self.cancel_visual_threat(send_off=False)
            self.neural_scheduler.interrupt(time.monotonic()*1000)
            if preserve_execution is None:
                self.clear_execution('stop')
            else:
                preserve_execution['stopRequestId'] = request_id
            self.stop_request = request_id
            self.stop_applied = False
        elif source == 'gpt' and self.active_execution is not None:
            self.active_execution['requestId'] = request_id
        timing = {}
        if intent_age_ms is not None:
            timing['intentAgeMs'] = intent_age_ms
        if execution_duration_ms is not None:
            timing['executionDurationMs'] = execution_duration_ms
        self.log('command_submitted', requestId=request_id, commandId=command_id, action=action, source=source, **timing)
        await self.adapter.send_action(action, request_id)
        self.emit({'type': 'command_result', 'stage': 'submitted', 'commandId': command_id,
                   'requestId': request_id, 'action': action, 'epoch': self.arbiter.epoch,
                   'message': self.text('submitted')})
        return request_id

    async def notify_application(self, request_id, item):
        # Complete the original delegation with verified application evidence.
        # This runs outside the Brain reader and never submits an operation.
        if ((not item.get('delegationId') and not item.get('notifyLive')) or item.get('applicationNoticeSent')
                or not item.get('applied') or item.get('rejected') or item.get('superseded')
                or item['epoch'] != self.arbiter.epoch or request_id != self.request_counter
                or item['conversationGeneration'] != self.conversation_generation
                or item['contextGeneration'] != self.conversation.context_generation
                or self.conversation_interaction != 'control' or not self.conversation_accepting
                or self.conversation.state != 'live' or self.arbiter.inhibited or self.arbiter.owner != 'gpt'):
            return
        item['applicationNoticeSent'] = True
        content = ('Command processing completed: Brain applied ' + item['action'] +
                   '. The backend owns the remaining execution and stopping checks. '
                   'Body movement/settling is not verified by this result. '
                   'Ready for the next player request, including a repeated command or condition update; '
                   'delegate it as a new request.')
        await self.conversation.append('thinking', content, item['delegationId'])

    def require_fresh(self):
        if not self.adapter or not self.adapter.connected or self.summary()['stale']:
            raise ControlError('fresh_brain_required')

    async def brain_message(self, event):
        kind = event['type']
        if kind == 'status':
            identity = tuple(event.get(k) for k in ('instanceId', 'sessionId', 'backendId', 'datasetId'))
            if self.brain_identity is not None and identity != self.brain_identity:
                self.stop_conversation_session()
                self.clear_neural()
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
                if item.get('delegationId'):
                    self.task(self.notify_application(rid, item))
            self.emit(event)
            # Preserve the original upstream request ID and unmodified neural
            # values. Bounded rotation prevents unlimited raw-frame accumulation.
            self.log('frame', frame=event)
            if not self.arbiter.inhibited and self.motor_writer:
                outgoing = copy.deepcopy(event)
                outgoing['appliedRequestId'] = (item['unityId'] if item and item['source'] == 'manual_tcp'
                    and item['epoch'] == self.arbiter.epoch and item['unityGeneration'] == self.unity_generation else 0)
                self.motor_emit(outgoing)
            self.observe_visual_threat(event)
            # Read-only analysis happens after motor forwarding, with no API await.
            try:
                self.observe_neural(event)
            except Exception as exc:
                self.neural.reset()
                self.neural_scheduler.pending = None
                self.log('neural_observation_failed', error=type(exc).__name__)
        elif kind == 'ack':
            item = self.requests.get(event['requestId'])
            if item and item['epoch'] == self.arbiter.epoch:
                item['rejected'] = event['accepted'] is not True
                self.log('command_accepted', requestId=event['requestId'], commandId=item['commandId'], accepted=event['accepted'])
                self.emit({'type': 'command_result', 'stage': 'accepted', 'commandId': item['commandId'],
                           'requestId': event['requestId'], 'accepted': event['accepted']})
                if item['source'] == 'manual_tcp' and item['unityGeneration'] == self.unity_generation:
                    self.motor_emit({**event, 'requestId': item['unityId']})
        elif kind in ('error', 'adapter_error'):
            await self.inhibit('brain_transport_error', send_stop=False)
            self.emit({'type': 'error', 'error': 'brain_transport_error'})

    async def connect_brain(self, target):
        self.clear_neural()
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
                and (self.arbiter.owner != 'gpt' or self.conversation.state in ('live', 'mock', 'text'))
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
        if event.get('type') == 'player_speech_started':
            self.player_speech_started()
            return
        if event.get('type') == 'conversation_context_receipt':
            self.log('conversation_context_receipt', **{k: v for k, v in event.items() if k != 'type'})
            return
        if event.get('type') == 'audio':
            audible = event.pop('audible', True)
            now = time.monotonic()
            if now - self.conversation.last_voice_end_at < .15:
                # Live has no response.cancel/output-done event. Drop output
                # while input is voiced; never queue it for later replay.
                return
            if audible:
                self.neural_output_at = now*1000
        elif event.get('type') == 'conversation_text' and event.get('role') == 'user':
            if not self.conversation_accepting or not event.get('text', '').strip():
                return
            now = time.monotonic()
            # One redirect per utterance burst; later ASR fragments must not
            # repeatedly erase the answer already being produced.
            if now - self.player_transcript_at >= 1.5:
                self.player_speech_started()
                await self.conversation.append('instructions',
                    'プレイヤーが話しかけています。現在の台本・実況を中断し、最新の発話を優先して聞いて応答してください。'
                    '中断した台本は再開しないでください。操作依頼の委任規則は維持してください。'
                    if self.conversation.settings['language'] == 'ja' else
                    'The player is speaking. Interrupt the current script or commentary, listen and respond to the latest utterance first. '
                    'Do not resume the interrupted script. Preserve operation delegation rules.')
            self.player_transcript_at = now
            self.neural_user_input(event.get('text'))
        if event['type'] == 'voice_test_diagnostic':
            if self.voice_test_observation and event.get('event') in VOICE_TEST_EVENTS:
                self.log(event['event'], **{k: v for k, v in event.items() if k in VOICE_TEST_FIELDS})
            return
        if event['type'] in ('audio', 'conversation_text') and not self.conversation_accepting:
            return
        if event['type'] == 'error':
            # Only our bounded numeric counters and allowlisted error codes;
            # never persist API messages, transcripts, or audio payloads.
            self.log('conversation_error', audioDiagnostics=self.conversation.diagnostics())
        if event['type'] == 'conversation_state':
            self.last_spoken_state = None
            self.conversation_announced = False
            if event['state'] in ('live', 'text'):
                self.player_priority_until = self.player_transcript_at = -1e15
                # A fresh voice session has no old-epoch audio awaiting ASR.
                self.voice_control_epoch = self.arbiter.epoch
                if self.conversation_interaction == 'chat_only' and self.conversation_accepting:
                    self.task(self.conversation.append('commentary',
                        'Greet the player briefly once in the configured language and invite them to talk. '
                        'This is conversation-only mode; no current Brain observations are available.'))
            if event['state'] not in ('live', 'mock', 'text') and self.arbiter.owner == 'gpt':
                await self.inhibit('conversation_disconnected')
            self.emit(self.state())
            self.log('conversation_state', state=event['state'],
                     audioDiagnostics=self.conversation.diagnostics())
        self.emit(event)

    async def voice_utterance(self, text, delegation_id, generation):
        self.neural_user_input(text)
        if generation == self.conversation.context_generation:
            if self.conversation_interaction == 'chat_only':
                # Do not invoke Responses or construct an Action in this mode.
                if self.conversation_accepting:
                    await self.conversation.append('commentary',
                        'Conversation only. No action was executed. Current Brain observations are unavailable. '
                        'Continue the conversation; explain that body control is disabled if requested.', delegation_id)
                return
            if self.is_local_visual_question(text):
                await self.answer_local_visual_question(text, delegation_id)
                return
            command_id = 'voice-' + str(uuid.uuid4())
            try:
                self.start_intent(text, command_id, self.arbiter.epoch, delegation_id)
                self.log('voice_intent_dispatch', outcome='started', commandId=command_id,
                         delegationId=delegation_id)
            except ControlError as exc:
                self.log('voice_intent_dispatch', outcome='rejected', reason=str(exc))
                self.emit({'type': 'error', 'error': str(exc)})
        else:
            self.log('voice_intent_dispatch', outcome='stale_context')

    async def transcript_utterance(self, text, candidate):
        self.neural_user_input(text)
        # Classification is speculative. A caption (including a question or an
        # incomplete correction) must not cancel any pending command by itself.
        epoch, revision = self.arbiter.epoch, self.intent_revision
        generation = self.conversation_generation
        if (not self.conversation.transcript_is_current(candidate)
                or not self.conversation_accepting or self.conversation_interaction != 'control'
                or self.voice_control_epoch != epoch or self.arbiter.inhibited or self.arbiter.owner != 'gpt'):
            return
        started = time.monotonic()
        context = self.intent_context()
        context['transcriptCandidate'] = True
        context['utteranceFinalized'] = candidate.get('finalized', False)
        if candidate.get('finalized') is True and self.is_local_visual_question(text):
            if self.conversation.claim_transcript(candidate):
                await self.answer_local_visual_question(text, candidate.get('delegationId'))
            return
        try:
            self.log('intent_classification_started', inputId=candidate['inputId'],
                     utteranceFinalized=context['utteranceFinalized'])
            proposal = await asyncio.wait_for(self.conversation.interpret(text, context,
                self.config['control']['defaultActionMs'], self.config['control']['maxActionMs']),
                self.config['control']['maxIntentAgeMs'] / 1000)
            validate_intent(proposal, self.config['control']['maxActionMs'])
            self.require_current_intent(started, epoch, revision)
            if (generation != self.conversation_generation or not self.conversation_accepting
                    or self.voice_control_epoch != epoch or self.arbiter.inhibited
                    or self.arbiter.owner != 'gpt' or not self.conversation.transcript_is_current(candidate)):
                return
            self.log('transcript_candidate_result', inputId=candidate['inputId'], kind=proposal['kind'])
            if proposal['kind'] not in ('action', 'plan', 'update'):
                # Reply through Live directly: start_intent would invalidate
                # pending control work even though this utterance has no Action.
                # Keep revisable clarification fragments available for a later
                # completion; finalized conversation can be consumed once.
                if candidate.get('finalized') is not True:
                    return
                if not self.conversation.claim_transcript(candidate):
                    return
                await self.speak_non_action(
                    self.non_action_reply_context(text, proposal['kind']), candidate.get('delegationId'))
                return
            if not self.conversation.claim_transcript(candidate):
                return
            command_id = candidate['inputId']
            self.start_intent(text, command_id, epoch, candidate.get('delegationId'), prepared={
                'proposal': proposal, 'context': context, 'started': started, 'voice': True,
                'interpretRoute': self.conversation.last_interpret_route,
                'transcriptRevision': self.conversation.transcript_revision,
                'contextGeneration': self.conversation.context_generation})
            self.log('voice_intent_dispatch', outcome='started', commandId=command_id,
                     inputId=candidate['inputId'], delegationId=candidate.get('delegationId'))
        except (ControlError, ConversationError, asyncio.TimeoutError, TimeoutError) as exc:
            # No accepted operation exists for this optional semantic check.
            self.log('transcript_candidate_result', inputId=candidate['inputId'],
                     outcome='rejected', reason='classification_timeout' if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else str(exc))

    def non_action_reply_context(self, text, kind, visual_direction=None):
        # Live already has the utterance. Keep a complete observation payload
        # inside ConversationAdapter.append's 380-character transport limit.
        if self.conversation_interaction == 'chat_only':
            return compact_summary(None, self.conversation.settings['language'], question=True,
                                   no_sarcasm=self.neural_scheduler.no_sarcasm)
        if self.neural.enabled and kind != 'local_visual_question' and self.conversation_interaction == 'control':
            return compact_summary(self.neural_snapshot(), self.conversation.settings['language'],
                                   question=True, no_sarcasm=self.neural_scheduler.no_sarcasm)
        context = self.intent_context()
        active = context.get('activeCommand')
        local = context.get('localSafety', {})
        payload = {'kind': kind,
                   'active': active.get('action') if active else None,
                   'brainApplied': active.get('brainApplied', False) if active else None,
                   'localFresh': local.get('fresh', False),
                   'facts': local.get('facts', {}) if local.get('fresh') else {},
                   'neuralStale': context.get('stale', True),
                   'neural': context.get('interpretation') if not context.get('stale', True) else None,
                   'scene': self.blind_script.current_fact()}
        visual = context.get('localVisual', {})
        description = self.local_visual.describe(visual_direction or 'all', self.conversation.settings['language'])
        if kind == 'local_visual_question':
            label = visual_direction or 'all'
            return ('プレイヤーの質問「' + str(text)[:48] + '」へ、観測された局所事実だけで回答する。ハエ基準の「' + label + '」方向。未確認は不明と述べ、安全を保証しない。'
                    + ' 観測: ' + description)[:379]
        payload['localVisualDescription'] = description if len(description) <= 180 else description.split('。')[0] + '。'
        instruction = ('最新の発言へ自然に回答。雑談は操作要求にしない。不明な操作だけ確認。'
                       '状態の質問には以下の観測を使い、一般質問にはその話題で答える。'
                       'brainAppliedは身体の動作成功ではない。')
        def encode():
            return instruction + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        # Omit whole optional fields rather than truncate JSON or factual text.
        for key in ('scene', 'neural', 'facts', 'neuralStale', 'brainApplied', 'localFresh', 'active'):
            if len(encode()) <= 380:
                break
            payload.pop(key, None)
        return encode()

    @staticmethod
    def local_visual_question_direction(text):
        if not isinstance(text, str):
            return None
        normalized = ''.join(text.strip().lower().split())
        normalized = normalized.rstrip('。.!！?？')
        exact = {
            '周りは': 'all', '周りには': 'all', '周りには何が見える': 'all', '何が見える': 'all',
            '右はどう': 'right', '右は危ない': 'right', '右に何がある': 'right',
            '左はどう': 'left', '左は危ない': 'left', '左に何がある': 'left',
            '前はどう': 'front', '前は危ない': 'front', '前に何がある': 'front',
            '後ろはどう': 'back', '後ろは危ない': 'back', '後ろに何がある': 'back',
            '前右はどう': 'front-right', '前左はどう': 'front-left',
            '後右はどう': 'back-right', '後左はどう': 'back-left',
            '右斜めはどう': 'front-right', '左斜めはどう': 'front-left',
            '右斜めに何がある': 'front-right', '左斜めに何がある': 'front-left',
            '右斜めは危ない': 'front-right', '左斜めは危ない': 'front-left',
            'whatisaround': 'all', 'whatcanyousee': 'all', 'whatisahead': 'front',
            'istherightsidedangerous': 'right', 'whatisontheright': 'right',
            'istheleftsidedangerous': 'left', 'whatisontheleft': 'left'}
        return exact.get(normalized)

    @classmethod
    def is_local_visual_question(cls, text):
        return cls.local_visual_question_direction(text) is not None

    async def answer_local_visual_question(self, text, delegation_id=None):
        if not self.conversation_accepting or self.conversation.state != 'live':
            return
        direction = self.local_visual_question_direction(text) or 'all'
        context = self.non_action_reply_context(text, 'local_visual_question', direction)
        epoch = self.arbiter.epoch
        generation = self.conversation_generation
        context_generation = self.conversation.context_generation
        self.local_visual.last_spoken_at = time.monotonic()  # Give the requested answer room before ambient speech.
        await self.conversation.append('commentary', context, delegation_id)
        if (epoch != self.arbiter.epoch or generation != self.conversation_generation
                or context_generation != self.conversation.context_generation):
            return
        self.emit({'type': 'local_visual_reply', 'sequence': self.local_visual.sequence,
                   'fresh': self.local_visual.summary()['fresh'], 'direction': direction,
                   'conversationGeneration': self.conversation_generation})

    def start_intent(self, text, command_id, epoch, delegation_id=None, *, prepared=None):
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
        kwargs = {'prepared': prepared} if prepared is not None else {}
        self.task(self.player_intent(text, command_id, epoch, self.intent_revision, delegation_id, **kwargs), intent=True)

    def require_current_intent(self, started, epoch, revision):
        if epoch != self.arbiter.epoch or revision != self.intent_revision:
            raise ControlError('stale_intent')
        age_ms = (time.monotonic() - started) * 1000
        if age_ms >= self.config['control']['maxIntentAgeMs']:
            raise ControlError('expired_intent')
        return age_ms

    async def player_intent(self, text, command_id, epoch, revision, delegation_id, *, prepared=None):
        started = time.monotonic() if prepared is None else prepared['started']
        voice = delegation_id is not None or (prepared is not None and prepared.get('voice', False))
        notice_generation = self.conversation_generation
        notice_context_generation = self.conversation.context_generation
        replaced_plan = False
        updating_conditions = False
        def check_transcript():
            if (notice_generation != self.conversation_generation
                    or notice_context_generation != self.conversation.context_generation):
                raise ControlError('stale_conversation_context')
            if prepared is not None and (prepared['transcriptRevision'] != self.conversation.transcript_revision
                    or prepared['contextGeneration'] != self.conversation.context_generation):
                raise ControlError('stale_transcript')
        try:
            check_transcript()
            context = self.intent_context() if prepared is None else prepared['context']
            proposal = (await self.conversation.interpret(text, context,
                self.config['control']['defaultActionMs'], self.config['control']['maxActionMs'])
                if prepared is None else prepared['proposal'])
            if any(k in proposal for k in ('operation', 'executionMode', 'distanceMeters')):
                validate_intent(proposal, self.config['control']['maxActionMs'])
            interpretation_ms = (time.monotonic()-started)*1000
            self.log('intent_classified', commandId=command_id,
                     source='voice' if voice else 'text',
                     kind=proposal['kind'],
                     action=proposal['action'] if proposal['kind'] == 'action' else None,
                     proposalValidForMs=proposal['validForMs'], interpretationMs=interpretation_ms,
                     plan=proposal.get('plan'), interpretRoute=(self.conversation.last_interpret_route
                        if prepared is None else prepared.get('interpretRoute')))
            self.require_current_intent(started, epoch, revision)
            check_transcript()
            if proposal['kind'] == 'update':
                if voice and self.voice_control_epoch != epoch:
                    raise ControlError('voice_session_restart_required')
                reference = context['activeCommand']
                if reference is None or proposal['targetExecutionId'] != reference['executionId']:
                    raise ControlError('stale_execution')
                updating_conditions = proposal['operation'] == 'modify_conditions'
                restarted = self.update_execution(proposal, command_id, epoch)
                if restarted is not None:
                    check_transcript()
                    intent_age_ms = self.require_current_intent(started, epoch, revision)
                    if self.active_execution is not restarted:
                        raise ControlError('stale_execution')
                    await self.submit(restarted['action'], 'gpt', command_id,
                                      intent_age_ms=intent_age_ms, delegation_id=delegation_id,
                                      **({'notify_live': True} if prepared is not None else {}))
                reply = proposal['reply'] or self.text('intent_sent')
                if self.active_execution is not None and self.active_execution.get('distancePhase') == 'braking':
                    reply = ('停止を確認しているよ。' if self.conversation.settings['language'] == 'ja'
                             else "I'm checking that I've stopped.")
            elif proposal['kind'] == 'action':
                if voice and self.voice_control_epoch != epoch:
                    raise ControlError('voice_session_restart_required')
                self.require_fresh()
                mode = proposal.get('executionMode', 'timed')
                if mode == 'distance':
                    self.distance_state(proposal.get('distanceMeters'), proposal['action'], None)
                replaced_plan = self.plans.active is not None
                if replaced_plan:
                    self.clear_execution('replaced')
                await self.plans.cancel_and_wait()
                intent_age_ms = self.require_current_intent(started, epoch, revision)
                check_transcript()
                self.require_fresh()
                # Interpretation/cancellation latency consumes the admission age
                # limit, never the accepted movement's execution duration.
                duration_ms = (self.config['control']['maxActionMs'] if proposal['action'] == 'STOP'
                               else proposal['validForMs'])
                if mode == 'distance':
                    self.local_observation.require_distance()
                self.arbiter.accept('gpt', proposal['action'], command_id, epoch, duration_ms,
                                    execution_mode=mode)
                if proposal['action'] != 'STOP':
                    self.activate_execution(command_id, proposal['action'], mode, self.arbiter.deadline,
                        **({'target_distance_meters': proposal['distanceMeters']} if mode == 'distance' else {}))
                await self.submit(proposal['action'], 'gpt', command_id,
                                  intent_age_ms=intent_age_ms,
                                  execution_duration_ms=0 if proposal['action'] == 'STOP' else duration_ms,
                                  **({'notify_live': True} if prepared is not None else {}),
                                  delegation_id=delegation_id)
                replaced_plan = False
                reply = self.text('intent_sent')
            elif proposal['kind'] == 'plan':
                if voice and self.voice_control_epoch != epoch:
                    raise ControlError('voice_session_restart_required')
                await self.plans.begin(proposal['plan'], command_id, epoch,
                                       self.conversation_generation, proposal['validForMs'],
                                       intent_deadline=started + self.config['control']['maxIntentAgeMs']/1000,
                                       revision=revision, execution_mode=proposal.get('executionMode', 'timed'),
                                       **({'distance_meters': proposal['distanceMeters']} if proposal.get('executionMode') == 'distance' else {}),
                                       admission_check=check_transcript,
                                       **({'notify_live': True} if prepared is not None else {}),
                                       **({'delegation_id': delegation_id} if delegation_id is not None else {}))
                reply = PLAN_REPLY[self.conversation.settings['language']][proposal['plan']]
            elif proposal['kind'] == 'question':
                reply = self.non_action_reply_context(text, proposal['kind'])
            else:
                reply = self.non_action_reply_context(text, proposal['kind'])
            if self.conversation.mode == 'text':
                if proposal['kind'] in ('question', 'clarify'):
                    reply = proposal['reply']
                self.emit({'type': 'conversation_text', 'role': 'assistant', 'text': reply, 'append': False})
            elif self.conversation.mode == 'mock':
                self.emit({'type': 'conversation_text', 'role': 'assistant', 'text': '[MOCK] ' + reply, 'append': False})
            else:
                # Voice Actions receive their result only when Brain application
                # is observed, so a late "sent" reply cannot follow completion.
                if not voice and proposal['kind'] in ('question', 'clarify'):
                    # Typed input was never heard by GPT-Live. Send its actual
                    # words as bounded, explicitly numbered context fragments;
                    # the final factual reply still has its own 380-char limit.
                    parts, part = [], ''
                    for character in text:
                        if len(json.dumps(part + character, ensure_ascii=False)) > 270:
                            parts.append(part)
                            part = ''
                        part += character
                    if part:
                        parts.append(part)
                    for index, part in enumerate(parts, 1):
                        check_transcript()
                        await self.conversation.append('thinking',
                            'Latest player typed question; join verbatim parts (' + str(index) + '/' + str(len(parts)) + '): '
                            + json.dumps(part, ensure_ascii=False))
                if proposal['kind'] != 'action' or not voice:
                    if proposal['kind'] in ('question', 'clarify'):
                        await self.speak_non_action(reply, delegation_id)
                    else:
                        await self.conversation.append('commentary', reply, delegation_id)
                if (proposal['kind'] == 'update' and voice
                        and epoch == self.arbiter.epoch and revision == self.intent_revision
                        and notice_generation == self.conversation_generation
                        and notice_context_generation == self.conversation.context_generation
                        and self.conversation_accepting and not self.arbiter.inhibited):
                    await self.conversation.append('thinking',
                        ('Execution update restarted the movement through the existing Brain Action. '
                         if restarted is not None else
                         'Execution update completed by the backend; no repeated Brain stimulus was needed. ')
                        + 'Ready for the next player request. Body movement is not verified by this update.',
                        delegation_id)
        except asyncio.CancelledError:
            if replaced_plan and not self.arbiter.inhibited:
                await self.inhibit('plan_replacement_cancelled')
            raise
        except (ControlError, ConversationError, BrainAdapterError) as exc:
            # A cancelled provider may still finish with an error. Its failure
            # cannot inhibit or speak over the newer execution/session.
            if (epoch != self.arbiter.epoch or revision != self.intent_revision
                    or notice_generation != self.conversation_generation
                    or notice_context_generation != self.conversation.context_generation):
                return
            if replaced_plan and not self.arbiter.inhibited:
                await self.inhibit('plan_replacement_failed')
            self.emit({'type': 'command_result', 'stage': 'rejected', 'commandId': command_id, 'reason': str(exc)})
            self.log('intent_rejected', commandId=command_id, reason=str(exc))
            if isinstance(exc, (ConversationError, BrainAdapterError)) and self.arbiter.owner == 'gpt':
                await self.inhibit('intent_service_failed')
            if updating_conditions and str(exc) in ('local_observation_unavailable',
                    'local_observation_unknown', 'edge_near', 'ground_missing', 'forward_blocked', 'body_unsafe'):
                await self.inhibit(str(exc))
            if epoch == self.arbiter.epoch:
                if str(exc) in ('local_observation_unavailable', 'local_observation_unknown'):
                    reply = ('周りがまだわからないから、進めない。' if self.conversation.settings['language'] == 'ja'
                             else "I can't move without a fresh view.")
                elif str(exc) in ('edge_near', 'ground_missing', 'forward_blocked', 'body_unsafe'):
                    reply = ('危険を感じるから、進めない。' if self.conversation.settings['language'] == 'ja'
                             else "I can't start with a hazard nearby.")
                else:
                    reply = self.text('rejected')
                await self.conversation.append('commentary', reply, delegation_id)

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

    async def accept_local_observation(self, event):
        if self.control_ws is None or self.conversation_interaction != 'control':
            raise ControlError('local_observation_control_required')
        if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
            raise ControlError('old_epoch')
        if (type(event.get('conversationGeneration')) is not int
                or event['conversationGeneration'] != self.conversation_generation):
            raise ControlError('old_conversation_generation')
        previous = self.local_observation.summary()
        try:
            self.local_observation.accept(event)
        except (ControlError, TypeError, KeyError):
            self.local_observation.sample = None
            if self.plans.active or (self.active_execution and self.active_execution['monitorHazards']):
                await self.inhibit('invalid_local_observation')
            raise ControlError('invalid_local_observation') from None
        concern = self.local_observation.concern(action=self.active_execution['action'] if self.active_execution else None)
        if not previous['fresh'] or previous['concern'] != concern:
            self.log('local_observation_received', sequence=self.local_observation.sequence,
                     reason=concern or 'clear')
        if concern and (self.plans.active or (self.active_execution and self.active_execution['monitorHazards'])):
            if self.plans.active:
                self.log('plan_stopped', planId=self.plans.active['planId'], reason=concern)
            await self.inhibit(concern)
        await self.warn_local_edge()

    async def accept_local_visual_observation(self, event):
        if (self.control_ws is None or self.conversation_interaction != 'control'
                or not self.conversation_accepting or self.conversation.state not in ('live', 'text')):
            raise ControlError('local_visual_observation_control_required')
        if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
            raise ControlError('old_epoch')
        if (type(event.get('conversationGeneration')) is not int
                or event['conversationGeneration'] != self.conversation_generation):
            raise ControlError('old_conversation_generation')
        previous = self.local_visual.summary()
        try:
            self.local_visual.accept(event)
        except (ControlError, TypeError, KeyError):
            self.local_visual.sample = None  # Withdraw invalid facts without rewinding the sequence watermark.
            raise ControlError('invalid_local_visual_observation') from None
        current = self.local_visual.summary()
        # Do not consume one-shot guidance while it must yield to the player.
        announcement = None if self.player_has_priority() else self.local_visual.announcement(language=self.conversation.settings['language'])
        self.emit({'type': 'local_visual_observation_result', 'sequence': self.local_visual.sequence,
                   'fresh': True, 'conversationGeneration': self.conversation_generation})
        if not previous['fresh'] or previous.get('facts') != current.get('facts'):
            self.log('local_visual_observation_received', sequence=self.local_visual.sequence,
                     reason=announcement['kind'] if announcement else 'clear')
        # Descriptive only; existing local safety warning remains authoritative.
        if announcement and not self.player_has_priority():
            self.local_visual_commentary_count += 1
            self.emit({'type': 'local_visual_commentary', 'sequence': self.local_visual.sequence,
                       'reason': announcement['kind'], 'count': self.local_visual_commentary_count,
                       'conversationGeneration': self.conversation_generation})
            facts = announcement['facts'].get('text', '')[:240]
            if self.conversation.mode == 'text':
                self.emit({'type': 'conversation_text', 'role': 'assistant', 'text': facts, 'append': False})
                return
            await self.conversation.append('commentary',
                '最新の局所センサーで確認した事実を' + ('一言だけ' if announcement['kind'] == 'hazard' else '短く') +
                '説明する。観測に含まれる橋の向き合わせは伝えてよい。'
                '未観測の進路や安全保証を足さず、案内から自動で操作しない。' + facts)

    async def warn_local_edge(self):
        scope = (self.arbiter.epoch, self.conversation_generation,
                 self.conversation.context_generation)
        if scope != self.edge_warning_scope:
            self.edge_warning_scope, self.edge_warning_sent = scope, False
        if (not self.conversation_accepting or self.conversation.state != 'live'
                or self.conversation_interaction != 'control' or self.control_ws is None
                or self.arbiter.inhibited or self.arbiter.owner != 'gpt'):
            return
        observation = self.local_observation.summary()
        if not observation['fresh']:
            return
        visual = self.local_visual.summary()
        if visual['fresh']:
            # The richer local visual producer owns speech; safety admission remains above.
            return
        facts = observation['facts']
        edges = (facts.get('leftEdge'), facts.get('rightEdge'))
        danger = facts.get('groundPresent') is False or any(
            edge in ('near', 'very_near') for edge in edges)
        safe = facts.get('groundPresent') is True and all(edge == 'safe' for edge in edges)
        if safe:
            self.edge_warning_sent = False
        elif danger and not self.edge_warning_sent and not self.player_has_priority():
            # One utterance per observed approach, not an Action or motor stop.
            # Unknown/stale samples do not rearm a continuing hazard.
            self.edge_warning_sent = True
            await self.conversation.append('commentary',
                '直近の局所Raycastで崖または足場切れを観測しました。'
                '「もうすぐ落ちそうです。」と一度だけ発話してください。停止操作は行いません。')

    async def blind_run_cue(self, event):
        # The existing sole control client is the trusted Unity game producer.
        # No second Brain connection, no Action submission, no camera controls.
        if (self.control_ws is None or not self.conversation_accepting
                or self.conversation.state not in ('live', 'text') or self.conversation_interaction != 'control'):
            raise ControlError('blind_live_control_required')
        if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
            raise ControlError('old_epoch')
        if (type(event.get('conversationGeneration')) is not int
                or event['conversationGeneration'] != self.conversation_generation):
            raise ControlError('old_conversation_generation')
        if self.switching or self.release_unknown:
            raise ControlError('blind_switch_in_progress')
        if event.get('cue') != 'link_error':
            self.require_fresh()
        text, speak = self.blind_script.accept(event, self.conversation.settings['language'])
        # A validated clear cue normally supplies thinking only. A measured
        # recent response can make that same cue one factual spoken report.
        measured = self.visual_threat_cue_context(event.get('cue'), text)
        if measured is not None:
            speak = True
            self.blind_script.last_cue = event['cue']
            self.blind_script.last_spoken_at = time.monotonic()
        if self.player_has_priority():
            speak = False
        if speak:
            self.neural_scheduler.interrupt(time.monotonic()*1000, 4000)
        # Send only the selected line, never the catalog, run ID or cue name.
        instruction = ('Blind Sugar Run。今回確認された場面のセリフだけを短く伝える。'
                       '意味を変えず一言に言い換えてよいが、事実・進路・原因を足さない。'
                       if self.conversation.settings['language'] == 'ja' else
                       'Blind Sugar Run. Use only this verified scene line. Keep it tiny; '
                       'paraphrase without adding facts, routes or causes. ')
        if self.conversation.mode == 'text':
            if speak:
                self.emit({'type': 'conversation_text', 'role': 'assistant', 'text': text, 'append': False})
        else:
            if measured is not None:
                await self.conversation.append('commentary' if speak else 'thinking', measured[0], trace=measured[1])
            else:
                await self.conversation.append('commentary' if speak else 'thinking',
                    instruction + text if speak else 'Observed scene context only; do not speak or resume this cue: ' + text)
        self.emit({'type': 'blind_run_cue_result', 'sequence': event['sequence'],
                   'stage': 'queued', 'speakRequested': speak})
        self.log('blind_run_cue_queued', cue=event['cue'], sequence=event['sequence'], speakRequested=speak)

    def accept_environment_event(self, event):
        required = {'type', 'kind', 'sourceId', 'runId', 'attempt', 'sequence', 'ageMs',
                    'controlEpoch', 'conversationGeneration', 'brainSequence', 'brainSessionId', 'brainInstanceId'}
        if set(event) != required:
            raise ControlError('invalid_environment_event')
        if (self.control_ws is None or not self.conversation_accepting or self.switching or self.release_unknown
                or self.conversation_interaction != 'control' or self.conversation.state not in ('live', 'text')):
            raise ControlError('environment_control_required')
        if type(event['controlEpoch']) is not int or event['controlEpoch'] != self.arbiter.epoch:
            raise ControlError('old_epoch')
        if type(event['conversationGeneration']) is not int or event['conversationGeneration'] != self.conversation_generation:
            raise ControlError('old_conversation_generation')
        self.require_fresh()
        status = self.adapter.status if self.adapter else {}
        frame = self.frame or {}
        if (event['brainSessionId'] != status.get('sessionId') or event['brainInstanceId'] != status.get('instanceId')
                or not event['brainSessionId'] or not event['brainInstanceId']
                or type(event['brainSequence']) is not int or event['brainSequence'] < 0
                or event['brainSequence'] > frame.get('sequence', -1)
                or frame.get('sequence', 0) - event['brainSequence'] > 16):
            raise ControlError('environment_brain_identity_mismatch')
        scope = (self.conversation_generation, status.get('sessionId'), status.get('instanceId'))
        if scope != self.environment_generation:
            self.environment.reset()
            self.environment_generation = scope
        observation = self.environment.accept(event, time.monotonic()*1000)
        if event['kind'] == 'run_started':
            self.cancel_visual_threat()
        elif observation is not None:
            if event['kind'] == 'threat_started':
                self.start_visual_threat(observation)
            elif event['kind'] in ('threat_ended', 'threat_cancelled', 'fall', 'swatted'):
                self.cancel_visual_threat(observe_off=True)
        if observation is None:
            return
        # Nonessential observations never fill the command queue or touch motor.
        if self.control_queue is not None and not self.control_queue.full() and self.control_queue.qsize() < 96:
            self.control_queue.put_nowait(observation)
        self.log('environment_observation', observation=observation)
        if self.environment_sender is None or self.environment_sender.done():
            self.environment_sender = self.task(self.send_environment_context(observation))

    async def send_environment_context(self, observation):
        if (observation['controlEpoch'] != self.arbiter.epoch or
                observation['conversationGeneration'] != self.conversation_generation or
                not self.conversation_accepting or self.switching or self.release_unknown or self.arbiter.inhibited
                or self.conversation_interaction != 'control' or self.conversation.state not in ('live', 'text')
                or self.adapter is None or not self.adapter.connected or self.summary()['stale']
                or observation['brainSessionId'] != self.adapter.status.get('sessionId')
                or observation['brainInstanceId'] != self.adapter.status.get('instanceId')):
            return
        fact = self.environment.summary(time.monotonic()*1000, self.conversation.settings['language'])
        if fact is None or self.environment.latest['sequence'] != observation['sequence']:
            return
        # Swatter/fall narration already exists. Contact alone may add one line.
        channel = 'commentary' if observation['kind'] == 'sugar_contact' and not self.player_has_priority() else 'thinking'
        if channel == 'commentary':
            fact += (' 設定中の人格で接触の事実だけを短い一言に。神経反応を創作しない。' if self.conversation.settings['language'] == 'ja'
                     else ' Keep the selected persona; briefly describe contact only. Do not invent a neural response.')
        await self.conversation.append(channel, fact)

    async def command(self, event):
        if not isinstance(event, dict):
            raise ControlError('invalid_message')
        kind = event.get('type')
        if kind == 'environment_event':
            self.accept_environment_event(event)
        elif kind == 'neural_observation_subscribe':
            if set(event) != {'type', 'controlEpoch', 'conversationGeneration', 'enabled'} or type(event.get('enabled')) is not bool:
                raise ControlError('invalid_neural_subscription')
            if (type(event['controlEpoch']) is int and event['controlEpoch'] == self.arbiter.epoch
                    and type(event['conversationGeneration']) is int and event['conversationGeneration'] == self.conversation_generation):
                self.neural_subscribed = self.neural.enabled and event['enabled']
        elif kind == 'body_response_observation':
            self.accept_neural_body(event)
        elif kind == 'voice_test_observation':
            if (set(event) != {'type', 'enabled'} or type(event['enabled']) is not bool
                    or self.control_ws is None):
                raise ControlError('invalid_voice_test_observation')
            self.voice_test_observation = event['enabled']
            self.conversation.voice_test_observation = event['enabled']
            self.emit({'type': 'voice_test_observation', 'enabled': event['enabled']})
        elif kind == 'configure_conversation':
            self.task(self.configure_conversation(event))
        elif kind == 'blind_run_cue':
            await self.blind_run_cue(event)
        elif kind == 'local_safety_observation':
            await self.accept_local_observation(event)
        elif kind == 'local_visual_observation':
            await self.accept_local_visual_observation(event)
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
            if 'controlEpoch' in event and (type(event['controlEpoch']) is not int
                                             or event['controlEpoch'] != self.arbiter.epoch):
                raise ControlError('old_epoch')
            if self.arbiter.owner == 'gpt' and self.conversation.state not in ('live', 'mock', 'text'):
                raise ControlError('conversation_not_started')
            if not self.resume_ready():
                raise ControlError('fresh_stopped_brain_required')
            self.arbiter.resume()
            self.log('resumed')
            self.emit(self.state())
        elif kind == 'set_action':
            if event.get('executionMode') == 'distance' or event.get('distanceMeters') is not None:
                raise ControlError('distance_requires_validated_intent')
            if self.conversation_interaction == 'chat_only':
                raise ControlError('chat_only_cannot_control')
            if self.motor_writer is not None:
                raise ControlError('manual_tcp_has_input_slot')
            self.require_fresh()
            self.arbiter.accept('manual', event.get('action'), event.get('commandId'),
                                event.get('controlEpoch'), event.get('validForMs'))
            await self.submit(event['action'], 'manual_ui', event['commandId'])
        elif kind == 'player_text':
            if (self.conversation_accepting and type(event.get('controlEpoch')) is int
                    and event['controlEpoch'] == self.arbiter.epoch
                    and isinstance(event.get('text'), str) and event['text'].strip()):
                self.player_speech_started()
            self.neural_user_input(event.get('text'))
            self.emit({'type': 'conversation_text', 'role': 'user', 'text': str(event.get('text', ''))[:2000], 'append': False})
            if self.conversation.mode != 'text' and self.is_local_visual_question(event.get('text')):
                if self.conversation_interaction == 'chat_only':
                    self.start_intent(event.get('text'), event.get('commandId'), event.get('controlEpoch'))
                if (not self.conversation_accepting or self.control_ws is None
                        or type(event.get('controlEpoch')) is not int
                        or event['controlEpoch'] != self.arbiter.epoch):
                    raise ControlError('old_epoch')
                await self.answer_local_visual_question(event.get('text'))
                return
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
            native_voice_control = event.get('nativeVoiceControl', False)
            if type(native_voice_control) is not bool:
                raise ControlError('invalid_native_voice_control')
            if native_voice_control and interaction != 'control':
                raise ControlError('native_voice_control_requires_control')
            if (self.conversation_operation is not None and not self.conversation_operation.done()
                    or self.conversation.state not in ('off', 'disconnected')):
                raise ControlError('conversation_already_started_or_stopping')
            if interaction == 'chat_only':
                if type(event.get('controlEpoch')) is not int or event['controlEpoch'] != self.arbiter.epoch:
                    raise ControlError('old_epoch')
                self.arbiter.set_owner('observer')
                await self.inhibit('chat_only')
            elif native_voice_control:
                if (type(event.get('controlEpoch')) is not int
                        or event['controlEpoch'] != self.arbiter.epoch):
                    raise ControlError('old_epoch')
                self.arbiter.set_owner('gpt')
                await self.inhibit('native_voice_control')
            self.conversation_interaction = interaction
            self.native_voice_control = native_voice_control
            self.conversation.interaction = interaction
            self.blind_script.reset()
            self.clear_neural()
            self.conversation_generation += 1
            self.local_observation.clear()
            self.local_visual.clear()
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
            else:
                if event.get('controlEpoch') != self.arbiter.epoch:
                    raise ControlError('old_audio_epoch')
                if 'conversationGeneration' in event and (
                        type(event['conversationGeneration']) is not int
                        or event['conversationGeneration'] != self.conversation_generation
                        or not self.conversation_accepting):
                    raise ControlError('old_conversation_generation')
            tag = None
            if 'fixtureId' in event or 'fixtureChunkIndex' in event:
                fid, index = event.get('fixtureId'), event.get('fixtureChunkIndex')
                if (not self.voice_test_observation or not isinstance(fid, str)
                        or not 1 <= len(fid) <= 64
                        or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in fid)
                        or type(index) is not int or not 0 <= index <= 100000):
                    raise ControlError('invalid_voice_fixture_tag')
                tag = {'fixtureId': fid, 'fixtureChunkIndex': index}
            if tag is None:
                await self.conversation.input_audio(event.get('audio'))
            else:
                await self.conversation.input_audio(event.get('audio'), tag)
        else:
            raise ControlError('unknown_message')

    def stop_conversation_session(self):
        self.clear_neural()
        had_plan = self.plans.active is not None
        had_execution = self.active_execution is not None
        self.plans.cancel()
        self.clear_execution('conversation_stopped')
        self.local_observation.clear()
        self.local_visual.clear()
        if had_plan or had_execution:
            self.task(self.inhibit('plan_conversation_stopped'))
        self.blind_script.reset()
        # Reserve the lifecycle operation synchronously: queued starts cannot
        # resurrect a session after Stop / WS disconnect / identity replacement.
        self.conversation_accepting = False
        self.native_voice_control = False
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

    def can_keep_voice_listening(self):
        return (self.native_voice_control and self.conversation_interaction == 'control'
                and self.conversation_accepting and self.arbiter.owner == 'gpt'
                and self.conversation.state in ('live', 'text')
                and self.voice_control_epoch == self.arbiter.epoch
                and not self.arbiter.inhibited
                and bool(self.adapter and self.adapter.connected)
                and not self.summary()['stale']
                and not self.switching and not self.release_unknown)

    async def finish_plan(self, plan, reason):
        if self.plans.active is not plan:
            return  # The newer instruction already owns the deadline and STOP.
        concern = self.local_observation.concern(action=PLAN_STEPS[plan['name']][plan['step']])
        keep_listening = (self.can_keep_voice_listening() and concern is None
                          and self.control_ws is not None and not self.closed)
        self.log('plan_stopped', planId=plan['planId'], reason=concern or reason,
                 continuedListening=keep_listening)
        # Consume this plan before yielding. A later command must survive the
        # previous plan's STOP delivery, like ordinary native Action expiry.
        self.plans.cancel()
        self.clear_execution(reason)
        if not keep_listening:
            await self.inhibit(concern or reason)
            return
        self.arbiter.deadline = None
        try:
            await self.submit('STOP', 'safety', 'plan-stop-' + str(uuid.uuid4()))
        except (ControlError, BrainAdapterError, ConnectionError, OSError):
            await self.inhibit('plan_stop_send_failed')
        self.emit(self.state())

    def distance_reason(self, execution, now):
        observation = self.local_observation
        travel = observation.require_distance(now)
        if observation.travel_fault_sequence > execution['distanceSequence']:
            raise ControlError(observation.travel_fault_reason)
        execution['distanceSequence'] = observation.sequence
        origin = execution['originTravelMeters']
        if origin is not None:
            if travel < origin:
                raise ControlError('distance_odometry_regressed')
            traveled = travel - origin
            execution['traveledMeters'] = traveled
            execution['remainingMeters'] = max(0.0, execution['targetDistanceMeters'] - traveled)
        if execution['distancePhase'] == 'braking':
            return self.distance_braking_reason(execution, now)
        if now - execution['distanceStartedAt'] >= 300:
            return 'distance_timeout'
        # The first turn of a new plan is deliberately excluded. A request
        # awaiting Brain application retains the separate finite apply timeout.
        item = self.requests.get(execution['requestId'], {})
        if origin is None or execution['action'] not in DISTANCE_ACTIONS or not item.get('applied'):
            return None
        if not execution['distanceApplied']:
            execution['distanceApplied'] = True
            execution['lastProgressAt'] = now
            execution['progressTravelMeters'] = execution['traveledMeters']
        # Initial control heuristic, not a neural/physics calibration: include
        # the observed movement speed when anticipating normal STOP's coast.
        if execution['remainingMeters'] <= observation.horizontal_speed * 1.2:
            return 'distance_approaching'
        if execution['traveledMeters'] - execution['progressTravelMeters'] >= 0.02 - 1e-9:
            execution['progressTravelMeters'] = execution['traveledMeters']
            execution['lastProgressAt'] = now
        if now - execution['lastProgressAt'] >= 8:
            return 'distance_stalled'
        return None

    def distance_braking_reason(self, execution, now):
        item = self.requests.get(execution['stopRequestId'], {})
        elapsed = now - execution['stopSentAt']
        if item.get('rejected') or item.get('superseded'):
            raise ControlError('distance_stop_not_applied')
        if not item.get('applied'):
            if elapsed >= 10:
                raise ControlError('distance_stop_apply_timeout')
            return None
        observation = self.local_observation
        travel = observation.travel_meters
        if observation.horizontal_speed >= .03:
            execution['settledSince'] = execution['settledTravelMeters'] = None
        elif (execution['settledSince'] is None
                or travel - execution['settledTravelMeters'] >= .01 - 1e-9):
            execution['settledSince'] = observation.sample_at
            execution['settledTravelMeters'] = travel
        elif observation.sample_at - execution['settledSince'] >= .5:
            # Silence/repeated watchdog polls cannot establish stability: the
            # fresh odometry timestamps must themselves span half a second.
            if execution['stopTrigger'] in ('distance_stalled', 'distance_timeout'):
                return execution['stopTrigger']
            target, traveled = execution['targetDistanceMeters'], execution['traveledMeters']
            tolerance = min(.5, max(.15, target * .1))
            if traveled > target + tolerance:
                return 'distance_overshoot'
            if traveled < target - tolerance or traveled < min(.05, target * .5):
                return 'distance_shortfall'
            return 'distance_reached'
        if elapsed >= 10:
            return 'distance_stop_unsettled'
        return None

    async def begin_distance_braking(self, execution, reason):
        if self.active_execution is not execution or execution['distancePhase'] != 'moving':
            return
        # Stop the runner before it can advance or repeat a phase. Keep this
        # execution as an observation-only stopping phase for "そのまま".
        if self.plans.active is not None and self.plans.active['executionId'] == execution['executionId']:
            self.plans.cancel()
        execution.update(distancePhase='braking', stopTrigger=reason, stopSentAt=time.monotonic(),
                         stopRequestId=None, settledSince=None, settledTravelMeters=None)
        self.arbiter.deadline = None
        self.log('execution_updated', executionId=execution['executionId'], distancePhase='braking',
                 stopTrigger=reason, **self.distance_summary(execution))
        self.emit(self.state())
        try:
            await self.submit('STOP', 'safety', 'distance-stop-' + str(uuid.uuid4()),
                              preserve_execution=execution)
        except (ControlError, BrainAdapterError, ConnectionError, OSError):
            # A newer instruction, including an explicit update, owns a new
            # object. A late completion/failure of this STOP cannot revoke it.
            if self.active_execution is execution:
                await self.inhibit('distance_stop_send_failed')

    async def finish_distance(self, execution, reason):
        if self.active_execution is not execution:
            return
        result = {'type': 'command_result', 'stage': 'execution_finished',
                  'executionId': execution['executionId'], 'commandId': execution['executionId'],
                  'reason': reason, 'completed': reason == 'distance_reached',
                  'epoch': self.arbiter.epoch, **self.distance_summary(execution)}
        # Normal STOP was already sent once when braking began. Consume only
        # this final observation; never send another stale STOP on completion.
        self.clear_execution(reason)
        self.arbiter.deadline = None
        # reached now requires STOP application plus fresh physical stability
        # and an actual traveled distance within the declared tolerance.
        self.emit(result)
        self.emit(self.state())

    async def check_control_safety(self):
        if self.arbiter.inhibited:
            return
        # A lost/frozen Brain always takes precedence over routine expiry.
        if self.summary()['stale']:
            await self.inhibit('stale_brain')
            return
        execution = self.active_execution
        if execution is not None:
            if (execution['epoch'] != self.arbiter.epoch
                    or execution['generation'] != self.conversation_generation
                    or self.arbiter.owner != 'gpt' or not self.conversation_accepting
                    or self.conversation.state not in ('live', 'mock', 'text') or self.closed
                    or self.switching or self.release_unknown):
                await self.inhibit('execution_context_lost')
                return
            if execution['monitorHazards']:
                concern = self.local_observation.concern(action=execution['action'])
                if concern:
                    await self.inhibit(concern)
                    return
            item = self.requests.get(execution['requestId'])
            if item and (item.get('rejected') or item.get('superseded')):
                await self.inhibit('execution_not_applied')
                return
            if item and not item['applied'] and time.monotonic() - item['sent'] >= self.config['control']['stopTimeoutMs'] / 1000:
                await self.inhibit('execution_apply_timeout')
                return
            if execution['executionMode'] == 'distance':
                try:
                    reason = self.distance_reason(execution, time.monotonic())
                except ControlError as exc:
                    await self.inhibit(str(exc))
                    return
                if reason:
                    if execution['distancePhase'] == 'braking':
                        await self.finish_distance(execution, reason)
                    else:
                        await self.begin_distance_braking(execution, reason)
                return
        if not self.arbiter.expired():
            return
        if self.plans.active:
            await self.finish_plan(self.plans.active, 'plan_expired')
            return
        keep_listening = self.can_keep_voice_listening()
        self.log('command_expired', continuedListening=keep_listening)
        if not keep_listening:
            await self.inhibit('command_expired')
            return
        # Consume only this deadline before yielding: a new command received
        # during STOP delivery must retain its own deadline and intent task.
        self.arbiter.deadline = None
        self.clear_execution('command_expired')
        try:
            await self.submit('STOP', 'safety', 'expired-stop-' + str(uuid.uuid4()))
        except (ControlError, BrainAdapterError, ConnectionError, OSError):
            await self.inhibit('expired_stop_send_failed')

    async def watchdog(self):
        while True:
            await asyncio.sleep(.1)
            await self.check_control_safety()
            self.emit(self.state())
            self.publish_execution_context()
            self.publish_neural()
            if self.visual_threat_source is not None and not self.visual_threat_scope_valid(self.visual_threat_source):
                self.cancel_visual_threat()
            if time.monotonic()-self.last_summary > 2:
                self.last_summary = time.monotonic()
                summary = self.summary()
                self.emit({'type': 'brain_summary', 'summary': summary})
                self.log('voice_pipeline', interaction=self.conversation_interaction,
                         state=self.conversation.state, owner=self.arbiter.owner,
                         outputInhibited=self.arbiter.inhibited,
                         neuralDiagnostics={'enabled': self.neural.enabled,
                             'pending': int(self.neural_scheduler.pending is not None),
                             'senderTasks': int(self.neural_sender is not None and not self.neural_sender.done()),
                             'allTasks': len(self.tasks), 'intentTasks': len(self.intent_tasks),
                             'controlQueueDepth': self.control_queue.qsize() if self.control_queue else 0,
                             'motorQueueDepth': self.motor_queue.qsize() if self.motor_queue else 0,
                             'contextAppends': self.neural_context_appends, 'maxSummaryChars': self.neural_max_chars},
                         audioDiagnostics=self.conversation.diagnostics())
                if self.conversation_interaction == 'chat_only':
                    continue  # General voice remains valid without fresh Brain data.
                if self.neural.enabled:
                    continue  # The bounded neural consumer owns observation commentary.
                local = self.local_observation.summary()
                brain_semantic = (summary['stale'], summary['interpretation'], self.arbiter.inhibited)
                # Do not resend merely because sequence/age changed at 10 Hz.
                semantic = (brain_semantic, local['fresh'], tuple(local['facts'].items()))
                if semantic != self.last_spoken_state:
                    brain_changed = self.last_spoken_state is None or self.last_spoken_state[0] != brain_semantic
                    self.last_spoken_state = semantic
                    context = json.dumps({'observation': summary['interpretation'],
                        'stale': summary['stale'], 'outputInhibited': self.arbiter.inhibited,
                        'localSafety': local,
                        'bodyMovementVerified': False}, ensure_ascii=False)
                    # Changes of *observed* state drive character speech; no
                    # speech is generated just because an action was requested.
                    channel = ('commentary' if brain_changed and self.conversation_announced and self.blind_script.run_id is None and not self.player_has_priority()
                               else 'thinking')
                    self.conversation_announced = self.conversation.state in ('live', 'mock', 'text')
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
                    event = await queue.get()
                    if event.get('type') == 'neural_response':
                        # Age durations belong to send time, not queue admission.
                        current = self.neural_snapshot()
                        if current is None:
                            continue
                        event = {'type': 'neural_response', **current}
                    elif event.get('type') == 'visual_threat_observation':
                        event = self.visual_threat_snapshot()
                        if event is None:
                            continue
                    elif event.get('type') == 'environment_observation':
                        current = self.environment.snapshot(time.monotonic()*1000)
                        if (current is None or current['controlEpoch'] != self.arbiter.epoch
                                or current['conversationGeneration'] != self.conversation_generation):
                            continue
                        event = current
                    await asyncio.wait_for(ws.send_json(event), timeout=2)
            sender = self.task(send())
            self.emit(self.state())
            self.emit(options_message())
            if self.frame:
                self.emit(self.frame)
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    event = None
                    try:
                        event = json.loads(message.data)
                        await self.command(event)
                    except (ValueError, TypeError, KeyError, BrainAdapterError, ConversationError) as exc:
                        self.emit(command_error_message(exc, event, self.arbiter.epoch))
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
                self.neural_subscribed = False
                self.control_ws = self.control_queue = None
                self.voice_test_observation = False
                self.conversation.voice_test_observation = False
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
                    if event.get('executionMode') == 'distance' or event.get('distanceMeters') is not None:
                        raise ControlError('distance_requires_validated_intent')
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
