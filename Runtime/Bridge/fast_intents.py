"""Closed grammar for already complete short requests, never partial-word control.

This function only proposes an intent. The caller owns final-utterance evidence,
deduplication, epochs, authority and the existing Brain execution path. Anything
outside the complete grammar returns None for the existing semantic interpreter.
"""
from decimal import Decimal, InvalidOperation
import math
import re

from .action_plans import validate_intent
from .control import ControlError


_JA_ACTIONS = {
    '前進': 'FORWARD',
    '前に進んで': 'FORWARD', '前へ進んで': 'FORWARD', '前進して': 'FORWARD',
    '進んで': 'FORWARD', '歩いて': 'FORWARD', '前に歩いて': 'FORWARD',
    '前へ歩いて': 'FORWARD',
    '止まって': 'STOP', '止まれ': 'STOP', '停止して': 'STOP',
    '停止': 'STOP', 'ストップ': 'STOP', 'とどまって': 'STOP',
    '右に曲がって': 'TURN_R', '右へ曲がって': 'TURN_R',
    '右を向いて': 'TURN_R', '右に向いて': 'TURN_R', '右': 'TURN_R',
    '左に曲がって': 'TURN_L', '左へ曲がって': 'TURN_L',
    '左を向いて': 'TURN_L', '左に向いて': 'TURN_L', '左': 'TURN_L',
}
_EN_ACTIONS = {
    'forward': 'FORWARD', 'right': 'TURN_R', 'left': 'TURN_L',
    'move forward': 'FORWARD', 'go forward': 'FORWARD',
    'walk forward': 'FORWARD', 'walk': 'FORWARD',
    'stop': 'STOP', 'stop moving': 'STOP', 'stop the fly': 'STOP', 'halt': 'STOP',
    'turn right': 'TURN_R', 'turn left': 'TURN_L',
}
# ASR may render a complete quantified imperative with a dictionary-form verb.
# Restrict this allowance to explicit quantities; bare narration stays semantic.
_JA_QUANTIFIED_FORWARD = frozenset(('前に進む', '前へ進む', '前進する', '進む', '歩く', '前に歩く', '前へ歩く'))
_NUMBER = r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)'
_JA_SECONDS = re.compile(r'(?P<amount>' + _NUMBER + r')\s*秒(?:間)?\s*(?P<body>.+)')
_EN_SECONDS = re.compile(r'(?P<body>.+) for (?P<amount>' + _NUMBER + r')\s*(?:seconds?|secs?|s)')
_JA_DISTANCE = re.compile(
    r'(?:約\s*)?(?P<amount>' + _NUMBER + r')\s*'
    r'(?P<unit>cm|センチメートル|センチ|m|メートル)'
    r'(?:ぐらい|くらい|ほど|程度)?\s*(?P<body>.+)')
_JA_HALF = re.compile(r'半(?:メートル|m)(?:ぐらい|くらい|ほど|程度)?\s*(?P<body>.+)')
_EN_DISTANCE = re.compile(
    r'(?P<body>move forward|go forward|walk forward|walk) (?:for )?'
    r'(?:(?:about|approximately) )?(?P<amount>' + _NUMBER + r')\s*'
    r'(?P<unit>cm|centimeters?|centimetres?|m|meters?|metres?)')
_EN_HALF = re.compile(r'(?P<body>move forward|go forward|walk forward|walk) (?:for )?half a (?:meter|metre)')
_JA_NUDGE = re.compile(r'(?:ちょっと|少し|もう少し)(?P<direction>右|左)(?P<verb>|を向いて|に向いて|に曲がって)')
_EN_NUDGE = re.compile(r'turn (?:a little|a bit|a touch|slightly) (?P<direction>right|left)')
_JA_LITTLE_FORWARD = frozenset(('ちょっと前へ', 'ちょっと前に進んで', '少し前へ', '少し前に進んで'))
_EN_LITTLE_FORWARD = frozenset(('a little forward', 'move a little forward', 'move forward a little', 'go a little forward'))


def _without_politeness(text):
    if text.startswith('please '):
        text = text[7:]
    elif text.endswith(', please'):
        text = text[:-8]
    elif text.endswith(' please'):
        text = text[:-7]
    for ending in ('ください', '下さい'):
        if text.endswith(ending) and text[:-len(ending)].endswith(('て', 'で')):
            return text[:-len(ending)]
    # Explicit direction requests with a polite imperative, not interrogatives.
    if text in ('右へお願いします', '右にお願いします', '右お願いします'):
        return '右'
    if text in ('左へお願いします', '左にお願いします', '左お願いします'):
        return '左'
    return text


def _meters(amount, unit):
    try:
        meters = Decimal(amount)
        if unit in ('cm', 'センチメートル', 'センチ', 'centimeter', 'centimeters', 'centimetre', 'centimetres'):
            meters /= 100
        return float(meters) if Decimal('0.05') <= meters <= 100 else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def fast_intent(text, context, default_ms, max_ms):
    """Return one complete nine-field proposal or None; never resolve context.

    context is reserved for the common interpreter signature. In particular,
    activeCommand cannot turn a fragment or "そのまま" into a fast operation.
    Empty reply leaves localized presentation to the existing Bridge path.
    """
    if (not isinstance(text, str) or not 0 < len(text) <= 160
            or any(character in text for character in ('\n', '\r', '\t', '?', '？', '…', '‥'))
            or '..' in text):
        return None
    if (type(default_ms) not in (int, float) or type(max_ms) not in (int, float)
            or not 0 < default_ms <= max_ms <= 8000
            or not math.isfinite(default_ms) or int(default_ms) != default_ms):
        return None
    normalized = text.strip().lower()
    # Strip one sentence terminator, not arbitrary syntax or quotation marks.
    if normalized.endswith(('。', '.', '!', '！')):
        normalized = normalized[:-1].rstrip()
    normalized = _without_politeness(normalized)
    if not normalized:
        return None

    def proposal(action=None, plan=None, duration=None, meters=None):
        result = {'kind': 'plan' if plan else 'action', 'action': action, 'plan': plan,
                  'validForMs': None if meters is not None else int(default_ms) if duration is None else duration,
                  'reply': '', 'operation': 'new',
                  'executionMode': 'distance' if meters is not None else 'timed',
                  'targetExecutionId': None, 'distanceMeters': meters}
        try:
            return validate_intent(result, max_ms)
        except ControlError:
            return None

    action = _JA_ACTIONS.get(normalized) or _EN_ACTIONS.get(normalized)
    if action is not None:
        return proposal(action=action)
    if normalized in _JA_LITTLE_FORWARD or normalized in _EN_LITTLE_FORWARD:
        return proposal(action='FORWARD', meters=0.5)
    for pattern in (_JA_NUDGE, _EN_NUDGE):
        match = pattern.fullmatch(normalized)
        if match:
            direction = match['direction']
            return proposal(plan='nudge_right' if direction in ('右', 'right') else 'nudge_left')
    for pattern in (_JA_SECONDS, _EN_SECONDS):
        match = pattern.fullmatch(normalized)
        if match:
            action = ('FORWARD' if match['body'] in _JA_QUANTIFIED_FORWARD else
                      _JA_ACTIONS.get(match['body']) or _EN_ACTIONS.get(match['body']))
            duration = Decimal(match['amount']) * 1000
            if (action in ('FORWARD', 'TURN_R', 'TURN_L') and 0 < duration <= max_ms
                    and duration == duration.to_integral_value()):
                return proposal(action=action, duration=int(duration))
            return None
    for pattern in (_JA_DISTANCE, _EN_DISTANCE, _JA_HALF, _EN_HALF):
        match = pattern.fullmatch(normalized)
        if match:
            action = ('FORWARD' if match['body'] in _JA_QUANTIFIED_FORWARD else
                      _JA_ACTIONS.get(match['body']) or _EN_ACTIONS.get(match['body']))
            if action != 'FORWARD':
                return None
            meters = _meters(match['amount'], match['unit']) if 'amount' in match.groupdict() else 0.5
            return proposal(action='FORWARD', meters=meters) if meters is not None else None
    return None
