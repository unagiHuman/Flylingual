"""Focused contract checks for the bounded English fixture vocabulary."""
import unittest

from Runtime.Bridge.fast_intents import fast_intent


class EnglishDemoIntentTests(unittest.TestCase):
    def parse(self, text, context=None):
        return fast_intent(text, {} if context is None else context, 4000, 8000)

    def test_demo_forward_stop_and_nudges_are_exact_complete_utterances(self):
        cases = (
            ('Keep moving forward until I tell you to stop.', 'action', 'FORWARD', None, 'until_next_command'),
            ('Okay, keep moving forward again.', 'action', 'FORWARD', None, 'timed'),
            ('Alright, stop here.', 'action', 'STOP', None, 'timed'),
            ('Alright stop here', 'action', 'STOP', None, 'timed'),
            ('All right Stop here', 'action', 'STOP', None, 'timed'),
            ('All right, stop here.', 'action', 'STOP', None, 'timed'),
            ('Okay keep moving forward again', 'action', 'FORWARD', None, 'timed'),
            ('Just a touch to the right.', 'plan', None, 'nudge_right', 'timed'),
            ('Just a touch to the left.', 'plan', None, 'nudge_left', 'timed'),
            ('A little more to the left.', 'plan', None, 'nudge_left', 'timed'),
        )
        for text, kind, action, plan, mode in cases:
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertIsNotNone(result)
                self.assertEqual(result['kind'], kind)
                self.assertEqual(result['action'], action)
                self.assertEqual(result['plan'], plan)
                self.assertEqual(result['executionMode'], mode)
        self.assertIsNone(self.parse('Keep moving forward until I tell you to stop.')['validForMs'])

    def test_good_keep_going_requires_an_observed_active_action(self):
        self.assertIsNone(self.parse('Good, keep going.'))
        result = self.parse('Good, keep going.', {'activeCommand': {
            'executionId': 'observed-forward-1', 'action': 'FORWARD'}})
        self.assertEqual(result['kind'], 'update')
        self.assertEqual(result['operation'], 'continue')
        self.assertEqual(result['executionMode'], 'inherit')
        self.assertEqual(result['targetExecutionId'], 'observed-forward-1')

    def test_casual_questions_never_propose_movement(self):
        for sentence in ('How are you feeling?', 'Are you hungry?', "What's it like being a fly?", 'How are you',
                         'Hey, how are you feeling today?', 'Are you feeling hungry right now?',
                         'What\u2019s it like being a fly?'):
            for text in (sentence, sentence.rstrip('?')):
                result = self.parse(text, {'activeCommand': {'executionId': 'walk', 'action': 'FORWARD'}})
                self.assertEqual(result['kind'], 'question')
                self.assertIsNone(result['action'])
                self.assertIsNone(result['targetExecutionId'])
        for text in ('Are you', 'How are you feeling? Stop.', 'Are you hungry, then move forward', 'Forward?'):
            self.assertIsNone(self.parse(text))

    def test_conditions_negatives_and_composites_do_not_become_demo_actions(self):
        unsafe_or_unsupported = (
            'If anything looks dangerous, stop.',
            "Don't stop here.",
            'Do not keep moving forward until I tell you to stop.',
            'Alright, stop here if blocked.',
            "Alright, let's get moving. Turn a little to the right, then keep going forward.",
            'Please repeat: alright, stop here.',
            'Good, keep going until I tell you to stop.',
            'Just a touch to the right, then move forward.',
            'Keep moving until I tell you to stop.',
        )
        for text in unsafe_or_unsupported:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))


if __name__ == '__main__':
    unittest.main()
