"""Game observations only. No neural stimulation, synthetic affect, or motor writes."""
from copy import deepcopy
import math
import re

from .control import ControlError

SOURCES = {'run_started': {'stage'}, 'sugar_contact': {'planning_juice', 'connection_juice'},
           'threat_started': {'idle_swatter'}, 'threat_ended': {'idle_swatter'},
           'threat_cancelled': {'idle_swatter'}, 'fall': {'fall'}, 'swatted': {'idle_swatter'}}
LINES = {
    'sugar_contact': ('通過中に果汁へ接触しました。', 'The fly contacted fruit juice while passing through.'),
    'threat_started': ('ハエたたきの警告が始まりました。', 'The fly swatter warning started.'),
    'threat_ended': ('移動してハエたたきの警告範囲を抜けました。', 'The fly moved out of the swatter warning area.'),
    'threat_cancelled': ('ハエたたきの観測が中断されました。回避成功かは不明です。', 'Swatter observation was interrupted; escape is unverified.'),
    'fall': ('落下を観測しました。', 'A fall was observed.'),
    'swatted': ('ハエたたきの命中を観測しました。', 'A fly swatter hit was observed.')}


class EnvironmentFeedback:
    def __init__(self, stale_ms=750):
        self.stale_ms = stale_ms
        self.reset()

    def reset(self):
        self.run = None
        self.attempt = 0
        self.sequence = -1
        self.consumed = set()
        self.terminal = False
        self.clear_current()

    def clear_current(self):
        self.latest = None
        self.threat = None
        self.received = None

    def accept(self, event, now_ms):
        kind, source = event.get('kind'), event.get('sourceId')
        run, attempt, sequence, age = (event.get(k) for k in ('runId', 'attempt', 'sequence', 'ageMs'))
        if (kind not in SOURCES or source not in SOURCES[kind] or type(run) is not str
                or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run) is None
                or type(attempt) is not int or not 1 <= attempt <= 2**31-1
                or type(sequence) is not int or not 0 < sequence <= 2**63-1
                or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= self.stale_ms):
            raise ControlError('invalid_environment_event')
        if kind == 'run_started':
            if self.run != run:
                if self.run is not None and attempt <= self.attempt:
                    raise ControlError('old_environment_attempt')
                self.reset()
                self.run, self.attempt = run, attempt
            if attempt != self.attempt or sequence <= self.sequence:
                raise ControlError('old_environment_sequence')
            self.sequence = sequence
            self.clear_current()
            return None
        if run != self.run or attempt != self.attempt or sequence <= self.sequence:
            raise ControlError('old_environment_run_or_sequence')
        self.sequence = sequence
        if self.terminal:
            return None
        if kind == 'sugar_contact':
            if source in self.consumed:
                return None
            self.consumed.add(source)
        elif kind == 'threat_started':
            if self.threat is True:
                return None
            self.threat = True
        elif kind in ('threat_ended', 'threat_cancelled'):
            if self.threat is not True:
                return None
            self.threat = False if kind == 'threat_ended' else None
        elif kind in ('fall', 'swatted'):
            self.terminal, self.threat = True, None
        self.received = now_ms
        self.latest = {'type': 'environment_observation', 'kind': kind, 'sourceId': source,
            'runId': run, 'attempt': attempt, 'sequence': sequence,
            'controlEpoch': event['controlEpoch'], 'conversationGeneration': event['conversationGeneration'],
            'brainSessionId': event['brainSessionId'], 'brainInstanceId': event['brainInstanceId'],
            'brainSequence': event['brainSequence'], 'ageMs': age, 'staleAfterMs': self.stale_ms,
            'fresh': True, 'evidenceSource': 'unity_environment', 'threatActive': self.threat,
            'neuralInputApplied': False, 'affectiveProxy': {'status': 'not_configured',
                'rewardAssociated': None, 'aversiveAssociated': None, 'subjectiveEmotionKnown': False}}
        return deepcopy(self.latest)

    def summary(self, now_ms, language):
        current = self.snapshot(now_ms)
        if current is None or not current['fresh']:
            return None
        return self.describe(current, language)

    def snapshot(self, now_ms):
        if self.latest is None:
            return None
        current = deepcopy(self.latest)
        age = now_ms - self.received + current['ageMs']
        current.update(ageMs=max(0, age), fresh=now_ms >= self.received and 0 <= age <= self.stale_ms)
        return current

    @staticmethod
    def describe(event, language):
        line = LINES[event['kind']][0 if language == 'ja' else 1]
        return (line + 'これはUnityの環境観測です。報酬・嫌悪の神経入力とreadoutは未定義で、神経反応・感情・学習は確認していません。'
                if language == 'ja' else line + ' This is a Unity environment observation. Reward/aversive neural inputs and readouts are not configured; neural affect, emotion, and learning are unverified.')
