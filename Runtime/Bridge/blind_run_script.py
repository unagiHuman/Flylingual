"""Backend-only cue sheet. Never send the catalog or route to the voice model.

Unity is the authority for local sensing and game events. This consumer only
validates bounded evidence and chooses speech; it never issues a Brain Action.
"""
import json
import time
from pathlib import Path

from .control import ACTIONS, ControlError


_CUES = json.loads(Path(__file__).with_name('blind_run_script.json').read_text(encoding='utf-8'))['cues']
_GROUNDS = {'unknown', 'desk', 'ruler', 'book', 'plate'}


class BlindRunScript:
    def __init__(self):
        self.reset()

    def reset(self):
        self.run_id = None
        self.attempt = 0
        self.sequence = 0
        self.once = set()
        self.last_fall = None
        self.fallen = False
        self.goal = False
        self.last_fact = None
        self.last_fact_at = 0
        self.last_cue = None
        self.last_spoken_at = 0

    def accept(self, event, language, now=None):
        now = time.monotonic() if now is None else now
        required = {'type', 'controlEpoch', 'conversationGeneration', 'runId', 'attempt',
                    'sequence', 'ageMs', 'cue', 'evidence'}
        if set(event) != required:
            raise ControlError('invalid_blind_cue_fields')
        run, attempt, sequence = event['runId'], event['attempt'], event['sequence']
        if (not isinstance(run, str) or not 1 <= len(run) <= 64
                or type(attempt) is not int or not 1 <= attempt <= 10000
                or type(sequence) is not int or not 1 <= sequence <= 2**53
                or type(event['ageMs']) not in (int, float) or not 0 <= event['ageMs'] <= 750):
            raise ControlError('invalid_or_stale_blind_cue')
        cue, evidence = event['cue'], event['evidence']
        if not isinstance(cue, str) or not isinstance(evidence, dict):
            raise ControlError('invalid_blind_cue')
        if language not in ('ja', 'en'):
            raise ControlError('invalid_blind_language')
        if cue == 'fall':
            if (set(evidence) != {'ground', 'lastAction', 'leftEdge', 'rightEdge', 'technicalFault'}
                    or any(not isinstance(evidence[k], str) for k in ('ground', 'lastAction', 'leftEdge', 'rightEdge'))
                    or evidence['ground'] not in _GROUNDS
                    or evidence['lastAction'] not in ACTIONS
                    or evidence['leftEdge'] not in ('unknown', 'near', 'very_near', 'safe')
                    or evidence['rightEdge'] not in ('unknown', 'near', 'very_near', 'safe')
                    or evidence['technicalFault'] is not False):
                raise ControlError('invalid_blind_fall')
            text = '落ちちゃった。' if language == 'ja' else 'I fell.'
        elif cue == 'retry':
            if evidence:
                raise ControlError('invalid_blind_retry')
            text = 'もう一回。' if language == 'ja' else 'One more try.'
            if self.last_fall:
                side = next((s for s in ('right', 'left') if self.last_fall[s + 'Edge'] == 'very_near'), None)
                if side:
                    text = (('前は、' + ('右' if side == 'right' else '左') + 'の端が近かった。')
                            if language == 'ja' else f'Last time, the {side} edge was very close.')
        else:
            item = _CUES.get(cue)
            # Exact typed, allowlisted evidence only: no route, free text or positions.
            if item is None or set(evidence) != set(item['evidence']) or any(
                    type(evidence[k]) is not type(v) or evidence[k] != v
                    for k, v in item['evidence'].items()):
                raise ControlError('blind_cue_evidence_mismatch')
            text = item[language]
        if self.run_id is None:
            if cue != 'intro' or attempt != 1:
                raise ControlError('blind_intro_required')
        elif run != self.run_id or sequence <= self.sequence:
            raise ControlError('old_blind_run_or_sequence')
        elif cue == 'retry':
            if not self.fallen or attempt != self.attempt + 1:
                raise ControlError('blind_retry_requires_fall')
        elif attempt != self.attempt:
            raise ControlError('old_blind_attempt')
        if self.fallen and cue not in ('retry', 'link_error'):
            raise ControlError('blind_retry_required')
        if self.goal and cue not in ('reveal', 'link_error'):
            raise ControlError('blind_goal_already_confirmed')
        if cue == 'reveal' and not self.goal:
            raise ControlError('blind_goal_required')
        self.run_id, self.attempt, self.sequence = run, attempt, sequence
        if cue == 'fall':
            self.fallen = True
            self.last_fall = dict(evidence)
        elif cue == 'retry':
            self.fallen = False
            self.last_fall = None  # One retrospective per retry, never infer a cause.
        elif cue == 'goal':
            self.goal = True
        elif cue == 'link_error':
            self.last_fall = None  # Technical failures are never gameplay memories.
        observed = cue in {'ruler_ahead', 'ruler_right', 'ruler_left', 'aligned',
                          'right_edge', 'right_edge_urgent', 'left_edge', 'left_edge_urgent',
                          'still_moving', 'stable', 'book', 'branch', 'branch_left_narrow',
                          'branch_right_narrow', 'plate', 'sugar', 'goal_wait'}
        self.last_fact = text if observed else None
        self.last_fact_at = now - event['ageMs'] / 1000
        one_shot = cue in {'intro', 'vision', 'ask', 'forward_lesson', 'turn_lesson',
                          'stop_lesson', 'retry', 'goal', 'reveal'}
        key = (attempt, cue)
        speak = key not in self.once if one_shot else (
            cue != self.last_cue and (now - self.last_spoken_at >= 3 or cue.endswith('_urgent') or cue in ('fall', 'link_error')))
        if one_shot:
            self.once.add(key)
        if speak:
            self.last_cue, self.last_spoken_at = cue, now
        return text, speak

    def current_fact(self):
        if self.last_fact is None or time.monotonic() - self.last_fact_at > .75:
            return None
        return self.last_fact
