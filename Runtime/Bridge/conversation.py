"""GPT-Live primary WebSocket + client-side intent delegation.

API contract: official live-delegation / voice-websockets guides, 2026-09-12.
No Realtime event aliases, SDK assumptions, automatic retry, or mock fallback.
"""
from __future__ import annotations

import asyncio
from array import array
import base64
from collections import deque
import json
import hashlib
import re
import math
import os
import sys
import time
import uuid

import aiohttp

from .intent_contract import INTENT_INSTRUCTIONS, INTENT_SCHEMA
from .intent_interpreter import interpret_intent, IntentInterpreterError
from .fast_intents import fast_intent
from .conversation_prompts import build_voice_instructions
from .conversation_settings import settings_from_config
from .translation import message_text, mock_intent

# Only stable identifiers are retained for diagnostics.  In particular, never
# copy API error messages, event bodies, transcript text, or PCM into state.
_API_ERROR_NAMES = frozenset({
    'api_error', 'authentication_error', 'conflict_error', 'internal_error',
    'invalid_audio', 'invalid_event', 'invalid_request_error', 'not_found_error',
    'permission_error', 'rate_limit_error', 'rate_limit_exceeded', 'server_error',
    'session_error', 'unprocessable_entity',
})
_LOCAL_EXCEPTION_NAMES = frozenset({
    'ClientError', 'ConnectionError', 'ConversationError', 'JSONDecodeError',
    'OSError', 'TimeoutError', 'TypeError', 'ValueError',
})


class ConversationError(RuntimeError):
    """Only stable, non-secret codes leave the API boundary."""


class ConversationAdapter:
    def __init__(self, config, on_event, on_utterance, on_transcript=None):
        self.config = config
        self.settings = settings_from_config({'conversation': config})
        self.mode = config['mode']
        self.interaction = 'control'
        self.on_event = on_event
        self.on_utterance = on_utterance
        self.on_transcript = on_transcript
        self.transcript_revision = 0
        self.transcript_changed_at = 0
        self.transcript_worker = None
        self.transcript_batch_delay = .25
        self.pending_delegations = deque(maxlen=160)
        self.transcript_event_ids = deque(maxlen=512)
        self.last_voice_end_ms = -1
        self.last_voice_end_at = -1
        self.last_interpret_route = None
        self.transcript_consumed_end = -1
        self.transcript_overflow = False
        self.last_input_end = -1
        self.state = 'off'
        self.http = None
        self.ws = None
        self.reader = None
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.closing = False
        self.fragments = deque(maxlen=160)
        self.delegations = deque(maxlen=512)
        self.last_offset = -1
        self.max_offset = -1
        self.context_generation = 0
        self.context_receipts = {}
        self.lifecycle = asyncio.Lock()
        self.audio_queue = asyncio.Queue(maxsize=24)
        self.audio_sender = None
        self.resolved_voice = None
        self._diagnostics = self._new_diagnostics()
        self.voice_test_observation = False
        self.sent_audio_samples = 0

    @staticmethod
    def _new_diagnostics():
        return {
            'inputChunks': 0,
            'inputBytes': 0,
            'sentInputChunks': 0,
            'sentInputBytes': 0,
            'clockSilenceChunks': 0,
            'inputTranscriptDeltas': 0,
            'outputTranscriptDeltas': 0,
            'outputAudioChunks': 0,
            'outputAudioBytes': 0,
            'outputZeroChunks': 0,
            'outputNonzeroChunks': 0,
            'delegationCount': 0,
            'delegationEventsSeen': 0,
            'delegationRejectedShape': 0,
            'delegationRejectedTarget': 0,
            'delegationRejectedId': 0,
            'delegationRejectedDuplicate': 0,
            'delegationRejectedOffset': 0,
            'timedInputTranscriptDeltas': 0,
            'untimedInputTranscriptDeltas': 0,
            'delegationWithTranscript': 0,
            'delegationWithoutTranscript': 0,
            'audioQueueDepth': 0,
            'audioQueueHighWater': 0,
            'audioBackpressureCount': 0,
            'lastErrorCode': None,
        }

    def diagnostics(self):
        """Return counter-only audio/session observations for the current session."""
        snapshot = dict(self._diagnostics)
        snapshot['audioQueueDepth'] = self.audio_queue.qsize()
        return snapshot

    def _reset_diagnostics(self):
        self._diagnostics = self._new_diagnostics()
        self.sent_audio_samples = 0

    def _record_error(self, code):
        if not self.closing:
            self._diagnostics['lastErrorCode'] = code

    @staticmethod
    def _api_error_code(event):
        error = event.get('error')
        if not isinstance(error, dict):
            return 'unknown'
        for field in ('code', 'type'):
            value = error.get(field)
            if isinstance(value, str) and len(value) <= 96 and value in _API_ERROR_NAMES:
                return value
        return 'unknown'

    @staticmethod
    def _local_error_code(error):
        name = type(error).__name__
        if name in _LOCAL_EXCEPTION_NAMES:
            return 'local_' + name
        return 'unknown'

    async def start(self):
        async with self.lifecycle:
            await self._start()

    async def _start(self):
        if self.state in ('connecting', 'live', 'mock', 'text'):
            return
        if self.http is not None:
            await self._stop(graceful=False)
        if self.mode == 'off':
            raise ConversationError('conversation_disabled')
        self._reset_diagnostics()
        self.closing = False
        self.started.clear()
        self.closed.clear()
        self.clear_context()
        self.resolved_voice = None
        if self.mode == 'text':
            self.http = aiohttp.ClientSession(trust_env=False)
            self.state = 'text'
            self.started.set()
            await self.on_event({'type': 'conversation_state', 'state': self.state})
            return
        if self.mode == 'mock':
            self.state = 'mock'
            await self.on_event({'type': 'conversation_state', 'state': self.state})
            return
        key = os.environ.get('OPENAI_API_KEY')
        if not key:
            raise ConversationError('api_key_missing')
        self.state = 'connecting'
        try:
            self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            self.ws = await self.http.ws_connect(
                'wss://api.openai.com/v1/live/sessions',
                headers={'Authorization': 'Bearer ' + key},
                max_msg_size=2 * 1024 * 1024, heartbeat=20,
            )
            # Transcript timestamps belong to this session's timeline.  A new
            # connection cannot reuse the previous session's cursor or IDs.
            # Same-session epoch invalidation still uses clear_context().
            self.last_offset = self.max_offset = -1
            self.transcript_consumed_end = self.last_input_end = -1
            self.transcript_overflow = False
            self.fragments.clear()
            self.delegations.clear()
            instructions = build_voice_instructions(self.settings, self.interaction,
                neural_feedback=getattr(self, 'neural_feedback_enabled', False))
            if self.interaction == 'control':
                instructions += ('\nBody-control mode: The player\'s standalone "止まって", '
                    '"止まれ", "ストップ", or "stop" requests stopping the fly. '
                    'Use client delegation immediately, including while you are speaking; '
                    'silencing your speech alone does not execute that request. '
                    'Only explicit speech requests such as "話すのをやめて" or '
                    '"stop talking" mean speech silence without a body action. '
                    'Do not treat negated stop requests as STOP. '
                    'Acknowledge body stopping only after the backend reports it.')
            await self.ws.send_json({'type': 'session.start', 'session': {
                'model': self.config['model'], 'instructions': instructions,
                'audio': {'format': {'type': 'audio/pcm', 'rate': 24000},
                          'output': {'voice': self.settings['voice']}},
                'delegation': {'type': 'client'},
            }})
            self.reader = asyncio.create_task(self._read(), name='gpt-live-reader')
            await asyncio.wait_for(self.started.wait(), timeout=15)
            if self.closed.is_set():
                raise ConversationError('live_start_failed')
            self.state = 'live'
            self.audio_sender = asyncio.create_task(self._send_audio(), name='gpt-live-audio-writer')
            await self.on_event({'type': 'conversation_state', 'state': self.state})
        except Exception:
            await self._stop(graceful=False)
            raise ConversationError('live_connect_failed') from None

    async def _read(self):
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    if message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
                    continue
                event = json.loads(message.data)
                kind = event.get('type')
                if kind == 'session.started':
                    self.resolved_voice = event.get('session', {}).get('audio', {}).get('output', {}).get('voice')
                    self.started.set()
                elif kind == 'session.closed':
                    break
                elif kind in ('session.thinking.appended', 'session.commentary.appended', 'session.instructions.appended'):
                    await self._context_appended(event)
                    if self.voice_test_observation:
                        await self.on_event({'type': 'voice_test_diagnostic',
                            'event': 'context_append_observed', 'outcome': kind})
                elif kind == 'error':
                    self._record_error(self._api_error_code(event))
                    raise ConversationError('live_api_error')
                elif kind == 'session.output_audio.delta':
                    if isinstance(event.get('delta'), str):
                        self._diagnostics['outputAudioChunks'] += 1
                        try:
                            output_pcm = base64.b64decode(event['delta'], validate=True)
                        except ValueError:
                            output_pcm = b''
                        self._diagnostics['outputAudioBytes'] += len(output_pcm)
                        if output_pcm:
                            if any(output_pcm):
                                self._diagnostics['outputNonzeroChunks'] += 1
                            else:
                                self._diagnostics['outputZeroChunks'] += 1
                        await self.on_event({'type': 'audio', 'audio': event['delta'],
                                             'audible': bool(output_pcm and any(output_pcm))})
                elif kind in ('session.input_transcript.delta', 'session.output_transcript.delta'):
                    text = event.get('delta', '')
                    if not isinstance(text, str):
                        continue
                    role = 'user' if kind == 'session.input_transcript.delta' else 'assistant'
                    event_id = event.get('event_id')
                    if role == 'user' and isinstance(event_id, str):
                        if event_id in self.transcript_event_ids:
                            continue
                        self.transcript_event_ids.append(event_id)
                    if role == 'user':
                        self._diagnostics['inputTranscriptDeltas'] += 1
                    else:
                        self._diagnostics['outputTranscriptDeltas'] += 1
                    await self.on_event({'type': 'conversation_text', 'role': role,
                                         'text': text, 'append': True})
                    if role == 'user':
                        start, end = event.get('start_ms'), event.get('end_ms')
                        if (type(start) in (int, float) and type(end) in (int, float)
                                and 0 <= start <= end < 10**12
                                and math.isfinite(start) and math.isfinite(end)):
                            self._diagnostics['timedInputTranscriptDeltas'] += 1
                            # A large gap retires abandoned non-command context;
                            # it never executes or cancels a command. Overflowed
                            # text is never truncated into an executable suffix.
                            if start > self.last_input_end + 1500 and self.last_input_end >= 0:
                                self.fragments.clear()
                                self.transcript_overflow = False
                            if len(self.fragments) == self.fragments.maxlen or len(text) > 2000:
                                self.transcript_overflow = True
                            self.fragments.append((start, end, text[:2000]))
                            if sum(len(f[2]) for f in self.fragments) > 2000:
                                self.transcript_overflow = True
                            self.last_input_end = max(self.last_input_end, end)
                            self.max_offset = max(self.max_offset, end)
                            self.transcript_revision += 1
                            self._schedule_transcript()
                            if self.voice_test_observation:
                                # Timing only: never persist captions or derive an action here.
                                await self.on_event({'type': 'voice_test_diagnostic',
                                    'event': 'input_transcript_observed',
                                    'startMs': start, 'endMs': end, 'transcriptChars': len(text)})
                        else:
                            self._diagnostics['untimedInputTranscriptDeltas'] += 1
                elif kind == 'session.delegation.created':
                    self._diagnostics['delegationEventsSeen'] += 1
                    delegation = event.get('delegation')
                    if not isinstance(delegation, dict):
                        self._diagnostics['delegationRejectedShape'] += 1
                        continue
                    if delegation.get('target') != 'client':
                        self._diagnostics['delegationRejectedTarget'] += 1
                        continue
                    did = delegation.get('id')
                    if not isinstance(did, str) or not 1 <= len(did) <= 256:
                        self._diagnostics['delegationRejectedId'] += 1
                        continue
                    if did in self.delegations:
                        self._diagnostics['delegationRejectedDuplicate'] += 1
                        continue
                    offset = event.get('offset_ms')
                    if (type(offset) not in (int, float) or not 0 <= offset < 10**12
                            or not math.isfinite(offset)):
                        self._diagnostics['delegationRejectedOffset'] += 1
                        continue
                    self.delegations.append(did)
                    self._diagnostics['delegationCount'] += 1
                    if self.on_transcript is not None and self.interaction == 'control':
                        # One application-owned receipt for both event routes.
                        # A late delegation joins the pending interpretation;
                        # it neither consumes its text nor cancels/restarts it.
                        if offset <= self.transcript_consumed_end:
                            self._diagnostics['delegationWithoutTranscript'] += 1
                            continue
                        self.pending_delegations.append((offset, did))
                        self._schedule_transcript(restart=False)
                        continue
                    # Transcript intervals are [start, end). A delegation can
                    # be stamped at the beginning of the already received last
                    # fragment; filtering by end cut complete words in half.
                    selected = [(start, end, t) for start, end, t in self.fragments
                                if start >= self.last_offset and start <= offset]
                    # Consume received fragments once, including zero-length
                    # intervals whose end alone cannot advance the cursor.
                    self.fragments = deque((fragment for fragment in self.fragments
                                            if fragment[0] > offset), maxlen=160)
                    self.transcript_revision += 1
                    text = '' if self.transcript_overflow else ''.join(t for _, _, t in selected).strip()
                    if self.voice_test_observation:
                        await self.on_event({'type': 'voice_test_diagnostic',
                            'event': 'delegation_observed', 'delegationId': did,
                            'transcriptChars': len(text),
                            'startMs': min((start for start, _, _ in selected), default=-1),
                            'endMs': max((end for _, end, _ in selected), default=-1),
                            'offsetMs': offset})
                    self.last_offset = max(self.last_offset, offset,
                                           max((end for _, end, _ in selected), default=-1))
                    # An event has no task text. Never invent one from its ID.
                    # The callback schedules interpretation; audio reading stays live.
                    if text:
                        self._diagnostics['delegationWithTranscript'] += 1
                        await self.on_utterance(text, did, self.context_generation)
                    else:
                        self._diagnostics['delegationWithoutTranscript'] += 1
                        if offset <= self.transcript_consumed_end:
                            # Application-owned classification already consumed
                            # this audio; do not announce a failed transcription.
                            continue
                        await self.append('commentary', message_text('incomplete_utterance', self.settings['language']), did)
        except asyncio.CancelledError:
            raise
        except ConversationError as error:
            if not self.closing:
                if str(error) not in ('live_api_error', 'live_send_failed'):
                    self._record_error(self._local_error_code(error))
                await self.on_event({'type': 'error', 'error': 'live_stream_failed'})
        except Exception as error:
            if not self.closing:
                self._record_error(self._local_error_code(error))
                await self.on_event({'type': 'error', 'error': 'live_stream_failed'})
        finally:
            self.context_receipts.clear()
            self.closed.set()
            self.started.set()
            self.state = 'off'
            if not self.closing:
                await self.on_event({'type': 'conversation_state', 'state': 'disconnected'})

    def clear_context(self):
        self.context_receipts.clear()
        self.context_generation += 1
        self.last_offset = max(self.last_offset, self.max_offset)
        self.fragments.clear()
        self.pending_delegations.clear()
        self.transcript_event_ids.clear()
        self.last_voice_end_ms = -1
        self.last_voice_end_at = -1
        self.transcript_overflow = False
        self.transcript_revision += 1
        if self.transcript_worker is not None:
            self.transcript_worker.cancel()
            self.transcript_worker = None
        while not self.audio_queue.empty():
            self.audio_queue.get_nowait()

    def _schedule_transcript(self, restart=True):
        if self.on_transcript is None or self.interaction != 'control':
            return
        if not restart and self.transcript_worker is not None:
            return
        if restart:
            self.transcript_changed_at = asyncio.get_running_loop().time()
        if self.transcript_worker is not None:
            self.transcript_worker.cancel()  # Speculative classification only.
        self.transcript_worker = asyncio.create_task(self._process_transcripts())

    async def _process_transcripts(self):
        # The delay batches model requests; it is NOT an end-of-turn signal or
        # permission to execute. Only a current semantic proposal can be claimed.
        try:
            while self.state == 'live' and not self.closing and self.interaction == 'control':
                revision = self.transcript_revision
                wait = self.transcript_batch_delay - (asyncio.get_running_loop().time() - self.transcript_changed_at)
                if wait > 0:
                    await asyncio.sleep(wait)
                if revision != self.transcript_revision:
                    continue
                fragments = tuple(fragment for fragment in self.fragments if fragment[0] >= self.last_offset)
                text = ''.join(fragment[2] for fragment in fragments).strip()
                if not text or len(text) > 2000 or self.transcript_overflow:
                    return
                # Live has transcript deltas, not Realtime's committed-turn
                # event. Require 300 ms of observed quiet for the fast route.
                # Legacy/no-audio callers retain semantic LLM validation.
                quiet = self.last_voice_end_ms >= 0 and self.sent_audio_samples / 24 - self.last_voice_end_ms >= 300
                # A noisy microphone must not lock out all commands. If the
                # acoustic boundary is unavailable, keep the original semantic
                # path after one second of stable text, with fast rules off.
                if self.last_voice_end_ms >= 0 and not quiet and asyncio.get_running_loop().time() - self.transcript_changed_at < 1.0:
                    await asyncio.sleep(.05)
                    continue
                finalized = quiet and self.sent_audio_samples / 24 >= max(f[1] for f in fragments)
                candidate = {'inputId': 'utterance-' + str(self.context_generation) + '-' + str(fragments[0][0]),
                             'generation': self.context_generation, 'revision': revision,
                             'fragments': fragments, 'finalized': finalized}
                if self.voice_test_observation:
                    await self.on_event({'type': 'voice_test_diagnostic',
                        'event': 'transcript_candidate_observed', 'inputId': candidate['inputId'],
                        'utteranceFinalized': finalized, 'speechEndMs': self.last_voice_end_ms,
                        'speechEndMonotonicMs': self.last_voice_end_at * 1000,
                        'startMs': min(f[0] for f in fragments), 'endMs': max(f[1] for f in fragments),
                        'offsetMs': max(f[1] for f in fragments), 'transcriptChars': len(text)})
                await self.on_transcript(text, candidate)
                if revision == self.transcript_revision:
                    return  # No automatic retry of the same text.
        finally:
            if self.transcript_worker is asyncio.current_task():
                self.transcript_worker = None

    def transcript_is_current(self, candidate):
        return (self.state == 'live' and not self.closing and self.interaction == 'control'
                and candidate['generation'] == self.context_generation
                and candidate['revision'] == self.transcript_revision)

    def claim_transcript(self, candidate):
        if not self.transcript_is_current(candidate):
            return False
        consumed = candidate['fragments']
        start = min(f[0] for f in consumed)
        end = max(f[1] for f in consumed)
        # Match IDs to the same session audio interval. Text equality would
        # incorrectly suppress the player repeating a command later.
        matching = [(offset, did) for offset, did in self.pending_delegations if start <= offset <= end]
        candidate['delegationId'] = matching[0][1] if matching else None
        self.pending_delegations = deque(((offset, did) for offset, did in self.pending_delegations
                                          if offset > end), maxlen=160)
        self.fragments = deque((f for f in self.fragments if f not in consumed), maxlen=160)
        self.last_offset = max(self.last_offset, max(f[1] for f in consumed))
        self.transcript_consumed_end = max(self.transcript_consumed_end, self.last_offset)
        self.transcript_revision += 1
        return True

    @staticmethod
    def _context_trace(trace):
        if trace is None:
            return None
        integer_keys = {'observationSequence', 'brainSequence', 'controlEpoch',
                        'conversationGeneration', 'requestId'}
        identity_keys = {'brainSessionId', 'brainInstanceId'}
        allowed = integer_keys | identity_keys | {'language', 'sourceId', 'active'}
        if type(trace) is not dict or not set(trace) <= allowed:
            raise ConversationError('invalid_context_trace')
        for key, value in trace.items():
            valid = False
            if key in integer_keys:
                valid = type(value) is int and -(2**63) <= value < 2**63
            elif key in identity_keys:
                valid = type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) is not None
            elif key == 'language':
                valid = value in ('ja', 'en')
            elif key == 'sourceId':
                valid = value == 'idle_swatter'
            elif key == 'active':
                valid = type(value) is bool
            if not valid:
                raise ConversationError('invalid_context_trace')
        return dict(trace)

    async def _context_receipt(self, record, stage, current):
        await self.on_event({'type': 'conversation_context_receipt', 'stage': stage,
            'eventId': record['eventId'], 'channel': record['channel'],
            'contextGeneration': record['generation'], 'contentHash': record['contentHash'],
            'trace': dict(record['trace']), 'current': current,
            **({'correlationField': record['correlationField']} if stage == 'accepted' else {})})

    async def _context_appended(self, event):
        channel = {'session.thinking.appended': 'thinking',
                   'session.commentary.appended': 'commentary',
                   'session.instructions.appended': 'instructions'}.get(event.get('type'))
        correlation_field = 'client_event_id' if 'client_event_id' in event else 'event_id'
        event_id = event.get(correlation_field)
        record = self.context_receipts.get(event_id) if type(event_id) is str else None
        if record is not None and time.monotonic()-record['createdAt'] > 30:
            self.context_receipts.pop(event_id, None)
            record = None
        if (record is None or record['channel'] != channel or self.closing
                or self.ws is None or self.ws.closed
                or record['generation'] != self.context_generation or record['ws'] is not self.ws):
            # Do not echo unknown IDs, values, content or server-provided key names.
            # These known schema keys are sufficient to diagnose correlation support.
            keys = sorted(set(event) & {'type', 'event_id', 'client_event_id', 'request_id',
                                       'request_event_id', 'source_event_id', 'item_id', 'content', 'session'})
            await self.on_event({'type': 'conversation_context_receipt', 'stage': 'unmatched',
                                'channel': channel, 'current': False, 'ackKeys': keys})
            return
        record['correlationField'] = correlation_field
        if not record['sent']:
            record['acknowledged'] = True
            return
        self.context_receipts.pop(event_id, None)
        await self._context_receipt(record, 'accepted', True)

    async def append(self, channel, content, delegation_id=None, *, trace=None):
        if self.mode != 'live' or self.ws is None or self.ws.closed or self.closing:
            return None
        if channel not in ('thinking', 'commentary', 'instructions'):
            raise ConversationError('invalid_context_channel')
        # Budget complete sentences before entry; never trim away uncertainty.
        if not isinstance(content, str) or len(content) > 380:
            raise ConversationError('conversation_context_too_long_or_invalid')
        safe_trace = self._context_trace(trace)
        event_id = str(uuid.uuid4())
        record = None
        if safe_trace is not None:
            record = {'eventId': event_id, 'channel': channel, 'generation': self.context_generation,
                      'contentHash': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                      'trace': safe_trace, 'ws': self.ws, 'sent': False, 'acknowledged': False,
                      'createdAt': time.monotonic()}
            self.context_receipts[event_id] = record
            while len(self.context_receipts) > 128:
                self.context_receipts.pop(next(iter(self.context_receipts)))
        try:
            await self._send_event({'type': 'session.' + channel + '.append',
                                   'event_id': event_id, 'delegation_id': delegation_id, 'content': content})
        except BaseException:
            self.context_receipts.pop(event_id, None)
            raise
        if record is not None:
            record['sent'] = True
            current = (self.context_receipts.get(event_id) is record and not self.closing
                       and record['generation'] == self.context_generation and record['ws'] is self.ws)
            await self._context_receipt(record, 'sent', current)
            if current and record['acknowledged'] and self.context_receipts.get(event_id) is record:
                self.context_receipts.pop(event_id, None)
                await self._context_receipt(record, 'accepted', True)
        return event_id

    async def input_audio(self, encoded, fixture_tag=None):
        if self.state != 'live':
            raise ConversationError('live_audio_not_connected')
        if not isinstance(encoded, str) or len(encoded) > 65536:
            raise ConversationError('invalid_audio')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ConversationError('invalid_audio') from None
        if not raw or len(raw) % 2:
            raise ConversationError('invalid_audio')
        self._diagnostics['inputChunks'] += 1
        self._diagnostics['inputBytes'] += len(raw)
        try:
            self.audio_queue.put_nowait((raw, dict(fixture_tag)) if fixture_tag is not None else raw)
        except asyncio.QueueFull:
            self._diagnostics['audioBackpressureCount'] += 1
            self._record_error('audio_backpressure')
            raise ConversationError('audio_backpressure') from None
        self._diagnostics['audioQueueHighWater'] = max(
            self._diagnostics['audioQueueHighWater'], self.audio_queue.qsize())

    async def _send_event(self, event):
        try:
            await asyncio.wait_for(self.ws.send_json(event), timeout=2)
        except Exception as error:
            self._record_error(self._local_error_code(error))
            self.state = 'off'
            await self.on_event({'type': 'conversation_state', 'state': 'disconnected'})
            raise ConversationError('live_send_failed') from None

    async def _send_audio(self):
        # GPT-Live advances on continuous input audio, including when a player
        # types or echo suppression pauses the microphone. Silence is transport
        # clocking only: it is never a fabricated transcript or a Brain input.
        silence = bytes(4800)  # 100 ms, PCM16 mono / 24 kHz.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + .1
        not_before = deadline
        try:
            while True:
                await asyncio.sleep(max(0, deadline - loop.time(), not_before - loop.time()))
                send_started = loop.time()
                try:
                    raw = self.audio_queue.get_nowait()
                    player_audio = True
                except asyncio.QueueEmpty:
                    raw = silence
                    player_audio = False
                tag = None
                if isinstance(raw, tuple):
                    raw, tag = raw
                audio_start = self.sent_audio_samples / 24
                context_generation = self.context_generation
                previous_voice_end = self.last_voice_end_at
                self._observe_voice_activity(raw)
                if (self.last_voice_end_at != previous_voice_end
                        and asyncio.get_running_loop().time() - previous_voice_end >= .6):
                    # Local envelope onset clears queued playback before ASR.
                    # It is presentation only, never an Action or a transcript.
                    await self.on_event({'type': 'player_speech_started'})
                await self._send_event({'type': 'session.input_audio.append',
                                        'audio': base64.b64encode(raw).decode('ascii')})
                self.sent_audio_samples += len(raw) // 2
                if (tag is not None and self.voice_test_observation
                        and context_generation == self.context_generation):
                    await self.on_event({'type': 'voice_test_diagnostic',
                        'event': 'audio_fixture_sent', **tag,
                        'audioStartMs': audio_start, 'audioEndMs': self.sent_audio_samples / 24})
                if player_audio:
                    self._diagnostics['sentInputChunks'] += 1
                    self._diagnostics['sentInputBytes'] += len(raw)
                else:
                    self._diagnostics['clockSilenceChunks'] += 1
                duration = len(raw) / 48000
                # Preserve the ideal PCM clock across ordinary scheduler jitter.
                # not_before bounds catch-up after a long write or suspension
                # without permanently shifting that ideal schedule.
                deadline += duration
                not_before = send_started + duration * .9
        except ConversationError:
            pass  # _send_event already reported the disconnect to the arbiter.

    def _observe_voice_activity(self, raw):
        samples = array('h')
        samples.frombytes(raw)
        if sys.byteorder != 'little':
            samples.byteswap()
        # Envelope only; no audio is saved and no words are inferred here.
        if samples and sum(x*x for x in samples) / len(samples) >= (32768 * .012) ** 2:
            self.last_voice_end_ms = (self.sent_audio_samples + len(raw) // 2) / 24
            self.last_voice_end_at = asyncio.get_running_loop().time() + len(raw) / 48000

    async def interpret(self, text, context, default_ms, max_ms):
        if self.state == 'mock':
            return {**mock_intent(text, default_ms, self.settings['language']), 'plan': None,
                    'operation': 'new', 'executionMode': 'timed', 'targetExecutionId': None,
                    'distanceMeters': None}
        if self.state not in ('live', 'text') or self.http is None:
            raise ConversationError('conversation_not_started')
        self.last_interpret_route = 'model'
        if not context.get('transcriptCandidate') or context.get('utteranceFinalized'):
            proposal = fast_intent(text, context, default_ms, max_ms)
            if proposal is not None:
                self.last_interpret_route = 'rules'
                return proposal
        try:
            return await interpret_intent(self.http, self.config, text, context,
                                          self.settings['language'], default_ms, max_ms)
        except IntentInterpreterError as error:
            raise ConversationError(str(error)) from None

    async def stop(self, graceful=True):
        async with self.lifecycle:
            await self._stop(graceful)

    async def _stop(self, graceful=True):
        self.closing = True
        self.context_receipts.clear()
        if self.transcript_worker is not None:
            self.transcript_worker.cancel()
            await asyncio.gather(self.transcript_worker, return_exceptions=True)
            self.transcript_worker = None
        if self.audio_sender is not None:
            self.audio_sender.cancel()
            await asyncio.gather(self.audio_sender, return_exceptions=True)
            self.audio_sender = None
        while not self.audio_queue.empty():
            self.audio_queue.get_nowait()
        if self.ws is not None and not self.ws.closed and graceful:
            try:
                await asyncio.wait_for(self.ws.send_json({'type': 'session.close'}), timeout=2)
                await asyncio.wait_for(self.closed.wait(), timeout=15)
            except (TimeoutError, ConnectionError, aiohttp.ClientError):
                pass
        if self.reader is not None and self.reader is not asyncio.current_task():
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.ws is not None:
            await self.ws.close()
        if self.http is not None:
            await self.http.close()
        self.ws = self.http = self.reader = None
        self.state = 'off'
        self.clear_context()
        await self.on_event({'type': 'conversation_state', 'state': 'off'})
