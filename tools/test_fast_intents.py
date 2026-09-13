"""Pure grammar/contract checks; no API, Brain, audio or body execution."""
import copy
import unittest

from Runtime.Bridge.action_plans import validate_intent
from Runtime.Bridge.fast_intents import fast_intent


class FastIntentTests(unittest.TestCase):
    def parse(self, text, **kwargs):
        return fast_intent(text, kwargs.get('context', {}), kwargs.get('default_ms', 4000),
                           kwargs.get('max_ms', 8000))

    def test_complete_simple_and_polite_requests(self):
        cases = {'前に進んで': 'FORWARD', '歩いてください。': 'FORWARD',
                 '止まって': 'STOP', '停止してください': 'STOP', 'とどまって': 'STOP',
                 '右に曲がって下さい': 'TURN_R', '左': 'TURN_L', '左へお願いします': 'TURN_L',
                 'Please move forward.': 'FORWARD', 'stop, please!': 'STOP', 'turn left': 'TURN_L'}
        for text, action in cases.items():
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertEqual(result['action'], action)
                self.assertEqual(result['executionMode'], 'timed')
                self.assertEqual(result['validForMs'], 4000)
                self.assertEqual(len(result), 9)
                self.assertIs(validate_intent(result, 8000), result)

    def test_explicit_seconds_preserve_duration(self):
        for text, milliseconds in (('8秒間前に進んで', 8000), ('8秒間前に進む', 8000),
                                   ('0.5秒右に曲がってください', 500),
                                   ('Please walk forward for 2 seconds.', 2000),
                                   ('turn left for .25s', 250)):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)['validForMs'], milliseconds)

    def test_distances_convert_units_without_inventing_time(self):
        cases = {'5mぐらい進んで': 5, '.5m前に進んで': .5, '半メートル進んで': .5,
                 '500cm進んでください': 5, '約5メートルほど歩いて': 5,
                 '5センチ前に進んで': .05, '100m進んで': 100,
                 'move forward about 5 meters': 5, 'please walk 50cm': .5,
                 'go forward half a metre': .5, '5mぐらい前に進む': 5}
        for text, meters in cases.items():
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertEqual(result['distanceMeters'], meters)
                self.assertEqual(result['action'], 'FORWARD')
                self.assertIsNone(result['validForMs'])
                self.assertEqual(result['executionMode'], 'distance')

    def test_short_turns_and_short_forward_remain_distinct(self):
        for text in ('ちょっと右', '少し右を向いてください', 'turn a touch right'):
            result = self.parse(text)
            self.assertEqual(result['plan'], 'nudge_right')
            self.assertIsNone(result['action'])
            self.assertEqual(result['executionMode'], 'timed')
        self.assertEqual(self.parse('もう少し左')['plan'], 'nudge_left')
        for text in ('ちょっと前へ', '少し前に進んで', 'move forward a little'):
            self.assertEqual(self.parse(text)['distanceMeters'], .5)

    def test_negations_questions_corrections_and_quoted_commands_never_match(self):
        cases = ('止まらないで', '前に進まないで', '右に曲がってはいけない',
                 'do not stop', "don't move forward", 'never walk',
                 '前に進んで？', '止まって?', '右は危ない？', 'Can you move forward?',
                 '右、いや左', 'walk, no stop', '前に進んでと言わないで',
                 '「止まって」', '"stop"', "'walk'", 'say stop',
                 '危険なら止まって', 'stop if blocked', '前に進んでから止まって',
                 '5mを8秒で進んで', 'walk 5m for 8 seconds', 'あそこまで進んで',
                 '砂糖まで歩いて', 'go forward to the sugar', '8秒間前に進む？',
                 '8秒間前に進むかもしれない', '8秒間前に進むな', '8秒間前に進むと言った')
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    def test_fragments_and_context_dependent_requests_use_semantic_path(self):
        context = {'activeCommand': {'executionId': 'existing', 'action': 'FORWARD'}}
        original = copy.deepcopy(context)
        for text in ('前', '前に', '止ま', '8秒間', '8秒間前に進ん', '前に進む',
                     '5m', '半メートル', 'turn', 'please',
                     '前に進んで…', 'walk...', 'そのまま', '続けて', 'そのままあと2m',
                     'もう少し前へ', 'keep going', 'walk until I say stop'):
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text, context=context))
        self.assertEqual(context, original)

    def test_bad_ranges_and_unknown_units_are_not_coerced(self):
        for text in ('0m進んで', '-5m進んで', '0.049m進んで', '101m進んで', 'NaNm進んで',
                     '5km進んで', '5mm進んで', '1e2m進んで', '0秒前に進んで',
                     '9秒前に進んで', '.0001秒前に進んで', '5m右に曲がって',
                     '5m止まって', '8秒止まって'):
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))
        self.assertIsNone(self.parse('4秒前に進んで', max_ms=3000, default_ms=2000))
        self.assertEqual(self.parse('前に進んで', max_ms=3000, default_ms=2000)['validForMs'], 2000)

    def test_input_and_configuration_are_bounded(self):
        for text in (None, 3, '', ' ', '歩いて\n止まって', 'walk\tforward', 'x' * 161):
            self.assertIsNone(self.parse(text))
        for overrides in ({'default_ms': True}, {'max_ms': float('inf')},
                          {'default_ms': 9000}, {'max_ms': 0}, {'default_ms': .5}):
            self.assertIsNone(self.parse('歩いて', **overrides))


if __name__ == '__main__':
    unittest.main()
