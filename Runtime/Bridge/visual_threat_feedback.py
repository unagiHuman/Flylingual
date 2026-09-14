"""Validate optional visual sensory observations without affecting motor processing."""
from copy import deepcopy
import math


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_readout(raw, window_ms):
    if not isinstance(raw, dict) or set(raw) != {'schemaVersion', 'stimulusModel', 'active', 'inputEventCount', 'requestId', 'reason', 'readouts'}:
        return None
    if (type(raw['schemaVersion']) is not int or raw['schemaVersion'] != 1
            or raw['stimulusModel'] != 'event_proxy_v1' or type(raw['active']) is not bool
            or type(raw['inputEventCount']) is not int or not 0 <= raw['inputEventCount'] <= 2**31-1
            or (raw['active'] is False and raw['inputEventCount'] != 0)
            or (raw['requestId'] is not None and type(raw['requestId']) is not int)
            or type(raw['reason']) is not str or not 1 <= len(raw['reason']) <= 128
            or not finite(window_ms) or window_ms <= 0
            or not isinstance(raw['readouts'], dict) or set(raw['readouts']) != {'R', 'L'}):
        return None
    for side, body_id in (('R', 10001), ('L', 10010)):
        item = raw['readouts'][side]
        if (not isinstance(item, dict) or set(item) != {'bodyId', 'spikeCount', 'rateHz'}
                or type(item['bodyId']) is not int or item['bodyId'] != body_id
                or type(item['spikeCount']) is not int or not 0 <= item['spikeCount'] <= 2**31-1
                or not finite(item['rateHz']) or item['rateHz'] < 0
                or not math.isclose(item['rateHz'], item['spikeCount'] * 1000 / window_ms, rel_tol=1e-6, abs_tol=1e-6)):
            return None
    return deepcopy(raw)


def describe(observation, language):
    raw = observation['raw']
    right, left = (raw['readouts'][side]['rateHz'] for side in ('R', 'L'))
    state = 'ON' if raw['active'] else 'OFF'
    if language == 'ja':
        return (f'今回のBrain窓で視覚危険イベント代理入力は{state}。同じ窓のDNp01実測発火率: 右{right:g} Hz、左{left:g} Hz。'
                '因果・恐怖・嫌悪・回避成功は未確認。設定中の人格を保ち、観測事実だけを短く伝える。')
    return (f'Visual threat event-proxy input was {state} in this Brain window. Measured DNp01 rates: '
            f'right {right:g} Hz, left {left:g} Hz. Causality, fear, aversion and escape are unverified. '
            'Keep the selected persona and state only these observations briefly.')

import time
from .brain_adapter import BrainAdapterError


class VisualThreatFeedbackMixin:
    def init_visual_threat(self):
        self.visual_threat_generation = 0
        self.visual_threat_source = None
        self.visual_threat_latest = None
        self.visual_threat_sender = None
        self.visual_threat_context_key = None
        self.visual_threat_last_context_ms = -1e15
        self.visual_threat_history = None
        self.visual_threat_history_sent = None

    def clear_visual_threat_history(self):
        self.visual_threat_history = None
        if self.visual_threat_sender is not None and not self.visual_threat_sender.done():
            self.visual_threat_sender.cancel()

    def visual_threat_scope(self):
        status = self.adapter.status if self.adapter else {}
        return (self.arbiter.epoch, self.conversation_generation, status.get('sessionId'),
                status.get('instanceId'), self.environment.run, self.environment.attempt)

    def visual_threat_scope_valid(self, source):
        return (source['scope'] == self.visual_threat_scope()
                and source['generation'] == self.visual_threat_generation
                and self.adapter is not None and self.adapter.connected
                and not self.switching and not self.release_unknown and not self.arbiter.inhibited
                and self.control_ws is not None and self.conversation_accepting
                and self.conversation_interaction == 'control' and not self.summary()['stale'])

    def cancel_visual_threat(self, send_off=True, observe_off=False):
        previous = self.visual_threat_source
        self.visual_threat_generation += 1
        self.visual_threat_source = self.visual_threat_latest = None
        if self.visual_threat_sender is not None and not self.visual_threat_sender.done():
            self.visual_threat_sender.cancel()
        adapter = self.adapter
        if adapter is not None and hasattr(adapter, 'invalidate_visual_threat'):
            adapter.invalidate_visual_threat()
        if previous is not None and send_off and adapter is not None and hasattr(adapter, 'send_visual_threat'):
            generation = self.visual_threat_generation
            source = {**previous, 'generation': generation, 'observe': observe_off}
            self.task(self.send_visual_threat_off(adapter, source, generation))

    async def send_visual_threat_off(self, adapter, source, generation):
        try:
            await adapter.send_visual_threat(False, 0, source=source,
                valid=lambda: adapter is self.adapter and generation == self.visual_threat_generation)
        except (BrainAdapterError, ConnectionError, OSError):
            self.log('visual_threat_off_unconfirmed')

    def start_visual_threat(self, observation):
        adapter = self.adapter
        if (adapter is None or not hasattr(adapter, 'send_visual_threat')
                or not isinstance(adapter.status.get('capabilities'), list)
                or 'visual_threat_v1' not in adapter.status['capabilities']):
            return
        self.cancel_visual_threat(send_off=False)
        source = {'scope': self.visual_threat_scope(), 'generation': self.visual_threat_generation,
                  'eventSequence': observation['sequence'], 'sourceId': observation['sourceId'],
                  'receivedMs': time.monotonic()*1000, 'initialAgeMs': observation['ageMs'], 'observe': True}
        self.visual_threat_source = source
        self.task(self.send_visual_threat_start(adapter, source))

    async def send_visual_threat_start(self, adapter, source):
        def valid():
            return (adapter is self.adapter and self.visual_threat_scope_valid(source)
                    and self.environment.threat is True
                    and time.monotonic()*1000-source['receivedMs']+source['initialAgeMs']
                        < min(750, self.config['control']['staleMs']))
        if not valid():
            return
        age = time.monotonic()*1000-source['receivedMs']+source['initialAgeMs']
        ttl = int(min(750, self.config['control']['staleMs'])-age)
        if ttl <= 0:
            return
        try:
            await adapter.send_visual_threat(True, ttl, source=source, valid=valid)
        except (BrainAdapterError, ConnectionError, OSError):
            self.log('visual_threat_start_unconfirmed')

    def observe_visual_threat(self, frame):
        adapter = self.adapter
        if (adapter is None or not isinstance(adapter.status.get('capabilities'), list)
                or 'visual_threat_v1' not in adapter.status['capabilities']):
            return
        self.visual_threat_latest = None
        raw_container = frame.get('raw')
        raw = validate_readout(raw_container.get('visualThreat') if isinstance(raw_container, dict) else None,
                               adapter.status.get('windowMs'))
        if raw is None:
            self.visual_threat_latest = None
            return
        pending = getattr(adapter, 'visual_threat_requests', {}).get(raw['requestId'])
        source = pending.get('source') if pending else None
        if not source or not source.get('observe') or not self.visual_threat_scope_valid(source):
            return
        status = adapter.status
        metadata = frame.get('metadata') or {}
        if (metadata.get('sessionId') != status.get('sessionId')
                or metadata.get('instanceId') != status.get('instanceId')):
            return
        now = time.monotonic()*1000
        self.visual_threat_latest = {'type': 'visual_threat_observation', 'raw': raw,
            'evidenceSource': 'brain_frame', 'stimulusModel': 'event_proxy_v1',
            'windowMs': adapter.status['windowMs'], 'inputValidForMs': pending.get('validForMs'),
            'brainSequence': frame['sequence'], 'brainSessionId': status['sessionId'],
            'brainInstanceId': status['instanceId'], 'controlEpoch': self.arbiter.epoch,
            'conversationGeneration': self.conversation_generation,
            'sourceId': source['sourceId'], 'environmentSequence': source['eventSequence'],
            'runId': source['scope'][4], 'attempt': source['scope'][5],
            'ageMs': 0, 'staleAfterMs': min(750, self.config['control']['staleMs']),
            'fresh': True, '_receivedMs': now, '_source': source}
        observation = self.visual_threat_snapshot()
        if observation is None:
            return
        history_key = (source['scope'], source['eventSequence'])
        if (raw['active'] and raw['inputEventCount'] > 0
                and any(item['spikeCount'] > 0 for item in raw['readouts'].values())
                and (self.visual_threat_history is None or self.visual_threat_history['key'] != history_key)):
            self.visual_threat_history = {'key': history_key, 'observedMs': now, 'observation': deepcopy(observation)}
            self.log('visual_threat_history', stage='captured', trace=self.visual_threat_trace(observation),
                     rightHz=raw['readouts']['R']['rateHz'], leftHz=raw['readouts']['L']['rateHz'])
        if self.control_queue is not None and not self.control_queue.full() and self.control_queue.qsize() < 96:
            self.control_queue.put_nowait(observation)
        key = (source['scope'], source['eventSequence'], raw['active'])
        if (key != self.visual_threat_context_key and now-self.visual_threat_last_context_ms >= 1500
                and (self.visual_threat_sender is None or self.visual_threat_sender.done())):
            self.visual_threat_sender = self.task(self.send_visual_threat_context(key))

    def visual_threat_snapshot(self):
        latest = self.visual_threat_latest
        if latest is None or not self.visual_threat_scope_valid(latest['_source']):
            return None
        age = time.monotonic()*1000-latest['_receivedMs']
        if not 0 <= age <= latest['staleAfterMs']:
            return None
        return {**{k: deepcopy(v) for k, v in latest.items() if not k.startswith('_')}, 'ageMs': age}

    async def send_visual_threat_context(self, key):
        observation = self.visual_threat_snapshot()
        if (observation is None or self.conversation.state not in ('live', 'text')
                or bool(self.intent_tasks) or time.monotonic()-self.conversation.last_voice_end_at < 1):
            return
        source = self.visual_threat_latest['_source']
        if key != (source['scope'], source['eventSequence'], observation['raw']['active']):
            return
        self.visual_threat_context_key = key
        self.visual_threat_last_context_ms = time.monotonic()*1000
        await self.conversation.append('thinking', describe(observation, self.conversation.settings['language']),
                                       trace=self.visual_threat_trace(observation))

    def visual_threat_trace(self, observation):
        return {key: observation[key] for key in ('brainSequence', 'brainSessionId', 'brainInstanceId',
                'controlEpoch', 'conversationGeneration', 'sourceId')} | {
                'observationSequence': observation['environmentSequence'],
                'requestId': observation['raw']['requestId'], 'active': observation['raw']['active'],
                'language': self.conversation.settings['language']}

    def visual_threat_cue_context(self, cue, text):
        """Attach one historical measurement to an already authorized scene line."""
        history = self.visual_threat_history
        if history is None or cue != 'swatter_escaped':
            return None
        now = time.monotonic()*1000
        if (history['key'][0] != self.visual_threat_scope() or now-history['observedMs'] > 8000
                or self.adapter is None or not self.adapter.connected or self.summary()['stale']
                or self.arbiter.inhibited or self.switching or self.release_unknown
                or not self.conversation_accepting or self.conversation_interaction != 'control'):
            self.clear_visual_threat_history()
            return None
        if (self.visual_threat_history_sent == history['key'] or not self.neural.enabled
                or self.neural_scheduler.reduced or not self.neural_scheduler.spontaneous
                or self.conversation.state != 'live'):
            return None
        observation = history['observation']
        right, left = (observation['raw']['readouts'][side]['rateHz'] for side in ('R', 'L'))
        if self.conversation.settings['language'] == 'ja':
            content = (f'短い1文だけ「さっきのDNp01は右{right:g}、左{left:g} Hz、予告は解除された」。'
                       '左右の実測値を省かない。先ほどの危険代理入力中の観測で、現在値や恐怖の測定ではない。前置きなし、設定中の口調を保つ。')
        else:
            content = (f'Say only one brief sentence: "Earlier DNp01: right {right:g}, left {left:g} Hz; warning cleared." '
                       'Keep both measured rates. These are earlier threat-proxy observations, not current readings or measured fear. No preamble; keep the configured tone.')
        if self.neural_scheduler.no_sarcasm:
            content += ' 皮肉なし。' if self.conversation.settings['language'] == 'ja' else ' No sarcasm.'
        if len(content) > 380:
            return None
        self.visual_threat_history_sent = history['key']
        return content, self.visual_threat_trace(observation)
