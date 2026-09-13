"""Closed output labels for the unchanged compact intent classification rules."""
import json
import re

from .local_intent import CODES, COMPACT_INSTRUCTIONS


CODE_TO_LABEL = {
    'STOP': 'S', 'FORWARD': 'F', 'TURN_R': 'R', 'TURN_L': 'L',
    'FORWARD_R': 'FR', 'FORWARD_L': 'FL',
    'nudge_right': 'NR', 'nudge_left': 'NL',
    'right_then_forward': 'RF', 'left_then_forward': 'LF',
    'forward_until_concern': 'FC', 'continue': 'CONT', 'conditions': 'COND',
    'question': 'Q', 'clarify': 'C',
}
if set(CODE_TO_LABEL) != set(CODES) or len(set(CODE_TO_LABEL.values())) != len(CODES):
    raise RuntimeError('intent_label_contract_mismatch')
LABEL_TO_CODE = {label: code for code, label in CODE_TO_LABEL.items()}
LABELS = tuple(CODE_TO_LABEL.values())
LABEL_JSON_SCHEMA = {'type': 'string', 'enum': list(LABELS)}
# Raw output grammar: JSON quotes below are GBNF literal delimiters, not output bytes.
LABEL_GBNF = 'root ::= ' + ' | '.join(json.dumps(label) for label in LABELS) + '\n'
LABEL_SCHEMA = LABEL_JSON_SCHEMA
LABEL_GRAMMAR = LABEL_GBNF


def decode_label(value):
    """Decode a complete raw label or an already parsed JSON string; never trim."""
    if type(value) is not str or value not in LABEL_TO_CODE:
        raise ValueError('invalid_intent_label')
    return LABEL_TO_CODE[value]


def label_to_compact(value):
    return {'c': decode_label(value)}


def _instructions():
    # Change only the output contract and class names, preserving every classification rule.
    original = 'JSON {"c":"種類"} だけを出力する。'
    if COMPACT_INSTRUCTIONS.count(original) != 1:
        raise RuntimeError('intent_label_prompt_contract_mismatch')
    prompt = COMPACT_INSTRUCTIONS.replace(original, '短いラベル一つだけを出力する。')
    prompt = prompt.replace('cの選択肢:', 'ラベルの選択肢:')
    # The source uses this abbreviation for the two directional plans.
    prompt = prompt.replace('*_then_forward', 'right_then_forward/left_then_forward')
    names = '|'.join(re.escape(code) for code in sorted(CODE_TO_LABEL, key=len, reverse=True))
    return re.sub(r'(?<![A-Za-z0-9_])(?:' + names + r')(?![A-Za-z0-9_])',
                  lambda match: CODE_TO_LABEL[match.group()], prompt)


# Fixed prefix: no user text, quantities, execution IDs or observations are interpolated here.
LABEL_INSTRUCTIONS = _instructions()
