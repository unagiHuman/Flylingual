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
# The English demo clips are deliberately grounded as complete normalized utterances.
# They are not substring rules and therefore cannot capture narration or conditions.
_EN_DEMO_PERSISTENT_FORWARD = frozenset(('keep moving forward until i tell you to stop',))
_EN_DEMO_FORWARD = frozenset(('okay, keep moving forward again', 'okay keep moving forward again'))
_EN_DEMO_STOP = frozenset(('alright, stop here', 'alright stop here',
                           'all right, stop here', 'all right stop here'))
_EN_DEMO_CONTINUE = frozenset(('good, keep going', 'good keep going'))
_EN_CASUAL_QUESTIONS = frozenset(('how are you feeling', 'how are you', 'are you hungry',
                                 'hey, how are you feeling today', 'hey how are you feeling today',
                                 'how are you feeling today', 'are you feeling hungry right now',
                                 'are you feeling hungry',
                                 "what's it like being a fly", 'what is it like being a fly'))
_EN_DEMO_NUDGES = {
    'just a touch to the right': 'nudge_right',
    'just a touch to the left': 'nudge_left',
    'a little more to the left': 'nudge_left',
}


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
    """Return one complete nine-field proposal or None.

    Only the complete English continuation phrase may target an observed active
    execution. Context cannot turn fragments or missing directions into movement.
    Empty reply leaves localized presentation to the existing Bridge path.
    """
    if (not isinstance(text, str) or not 0 < len(text) <= 160
            or any(character in text for character in ('\n', '\r', '\t', '…', '‥'))
            or '..' in text):
        return None
    if (type(default_ms) not in (int, float) or type(max_ms) not in (int, float)
            or not 0 < default_ms <= max_ms <= 8000
            or not math.isfinite(default_ms) or int(default_ms) != default_ms):
        return None
    normalized = text.strip().lower().replace('\u2019', "'")
    question_text = normalized[:-1].rstrip() if normalized.endswith(('?', '.', '!', '？')) else normalized
    if question_text in _EN_CASUAL_QUESTIONS:
        return validate_intent({'kind': 'question', 'action': None, 'plan': None,
            'validForMs': int(default_ms), 'reply': '', 'operation': 'new', 'executionMode': 'timed',
            'targetExecutionId': None, 'distanceMeters': None}, max_ms)
    if '?' in normalized or '？' in normalized:
        return None
    # Strip one sentence terminator, not arbitrary syntax or quotation marks.
    if normalized.endswith(('。', '.', '!', '！')):
        normalized = normalized[:-1].rstrip()
    normalized = _without_politeness(normalized)
    if not normalized:
        return None

    def proposal(action=None, plan=None, duration=None, meters=None, execution_mode='timed'):
        result = {'kind': 'plan' if plan else 'action', 'action': action, 'plan': plan,
                  'validForMs': None if meters is not None or execution_mode != 'timed' else int(default_ms) if duration is None else duration,
                  'reply': '', 'operation': 'new',
                  'executionMode': 'distance' if meters is not None else execution_mode,
                  'targetExecutionId': None, 'distanceMeters': meters}
        try:
            return validate_intent(result, max_ms)
        except ControlError:
            return None

    def continue_active():
        active = context.get('activeCommand') if isinstance(context, dict) else None
        execution_id = active.get('executionId') if isinstance(active, dict) else None
        action = active.get('action') if isinstance(active, dict) else None
        if (not isinstance(execution_id, str) or not 1 <= len(execution_id) <= 128
                or execution_id.strip() == '' or action not in ('FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L')):
            return None
        result = {'kind': 'update', 'action': None, 'plan': None, 'validForMs': None,
                  'reply': '', 'operation': 'continue', 'executionMode': 'inherit',
                  'targetExecutionId': execution_id, 'distanceMeters': None}
        try:
            return validate_intent(result, max_ms)
        except ControlError:
            return None

    if normalized in _EN_DEMO_PERSISTENT_FORWARD:
        return proposal(action='FORWARD', execution_mode='until_next_command')
    if normalized in _EN_DEMO_FORWARD:
        return proposal(action='FORWARD')
    if normalized in _EN_DEMO_STOP:
        return proposal(action='STOP')
    if normalized in _EN_DEMO_CONTINUE:
        return continue_active()
    nudge = _EN_DEMO_NUDGES.get(normalized)
    if nudge is not None:
        return proposal(plan=nudge)
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
