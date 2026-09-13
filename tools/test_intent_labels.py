"""Pure label/grammar/prompt contract checks; no model or physical execution."""
import json
import re
import unittest

from Runtime.Bridge.intent_labels import (
    CODE_TO_LABEL, LABEL_TO_CODE, LABELS, LABEL_JSON_SCHEMA, LABEL_GBNF,
    LABEL_INSTRUCTIONS, decode_label, label_to_compact,
)
from Runtime.Bridge.local_intent import CODES, COMPACT_INSTRUCTIONS


class IntentLabelTests(unittest.TestCase):
    def test_every_existing_code_maps_bijectively(self):
        self.assertEqual(set(CODE_TO_LABEL), set(CODES))
        self.assertEqual(len(LABELS), 15)
        self.assertEqual(len(set(LABELS)), 15)
        self.assertEqual(set(LABELS), {'S', 'F', 'R', 'L', 'FR', 'FL', 'NR', 'NL',
                                     'RF', 'LF', 'FC', 'CONT', 'COND', 'Q', 'C'})
        for code in CODES:
            self.assertEqual(decode_label(CODE_TO_LABEL[code]), code)
            self.assertEqual(label_to_compact(CODE_TO_LABEL[code]), {'c': code})

    def test_rejects_nonlabels_without_trimming_or_prefix_matching(self):
        for value in ('', ' ', '\n', 'F ', ' F', 'F\n', 'F explanatory text', 'FORWARD',
                      'CON', 'CO', 'N', 'UNKNOWN', 'f', 'Ｆ', '"F"', '{"c":"F"}',
                      'F,R', 'FRL', None, True, 1, {}, [], b'F'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^invalid_intent_label$'):
                decode_label(value)

    def test_shared_prefixes_require_a_complete_valid_label(self):
        # F/C are valid classes in their own right; partial CONT/COND strings are not.
        for value, expected in [('F', 'FORWARD'), ('FR', 'FORWARD_R'), ('FC', 'forward_until_concern'),
                                ('C', 'clarify'), ('CONT', 'continue'), ('COND', 'conditions')]:
            self.assertEqual(decode_label(value), expected)
        for value in ('CON', 'CONTINUE', 'CONDITION'):
            with self.assertRaises(ValueError):
                decode_label(value)

    def test_json_schema_is_string_enum_only(self):
        self.assertEqual(LABEL_JSON_SCHEMA, {'type': 'string', 'enum': list(LABELS)})
        for label in LABEL_JSON_SCHEMA['enum']:
            self.assertEqual(decode_label(json.loads(json.dumps(label))), LABEL_TO_CODE[label])

    def test_raw_grammar_accepts_only_the_complete_label_literals(self):
        self.assertTrue(LABEL_GBNF.startswith('root ::= '))
        expressions = LABEL_GBNF.removeprefix('root ::= ').strip().split(' | ')
        literals = [json.loads(expression) for expression in expressions]
        self.assertEqual(literals, list(LABELS))
        self.assertNotIn('[', LABEL_GBNF)
        self.assertNotIn('*', LABEL_GBNF)
        self.assertNotIn('ws', LABEL_GBNF)

    def test_prompt_preserves_rules_except_output_names(self):
        names = '|'.join(re.escape(label) for label in sorted(LABEL_TO_CODE, key=len, reverse=True))
        restored = re.sub(r'(?<![A-Za-z0-9_])(?:' + names + r')(?![A-Za-z0-9_])',
                          lambda match: LABEL_TO_CODE[match.group()], LABEL_INSTRUCTIONS)
        restored = restored.replace('短いラベル一つだけを出力する。', 'JSON {"c":"種類"} だけを出力する。')
        restored = restored.replace('ラベルの選択肢:', 'cの選択肢:')
        expected = COMPACT_INSTRUCTIONS.replace('*_then_forward', 'right_then_forward/left_then_forward')
        self.assertEqual(restored, expected)

    def test_replacement_does_not_damage_long_codes_or_context_names(self):
        self.assertIn('R/L: 右/左を向く。FR/FL:', LABEL_INSTRUCTIONS)
        self.assertIn('RF/LF:', LABEL_INSTRUCTIONS)
        self.assertIn('activeForward=trueならCONT', LABEL_INSTRUCTIONS)
        self.assertIn('candidate=true', LABEL_INSTRUCTIONS)
        self.assertNotIn('F_R', LABEL_INSTRUCTIONS)
        self.assertNotIn('*_then_forward', LABEL_INSTRUCTIONS)
        for code in CODES:
            self.assertIsNone(re.search(r'(?<![A-Za-z0-9_])' + re.escape(code) + r'(?![A-Za-z0-9_])', LABEL_INSTRUCTIONS))


if __name__ == '__main__':
    unittest.main()
