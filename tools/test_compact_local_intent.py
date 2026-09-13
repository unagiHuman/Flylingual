"""Pure compact-adapter tests; no Brain, Unity, real model or network is used."""
import asyncio
import copy
import json
import unittest

from Runtime.Bridge.intent_contract import INTENT_SCHEMA
from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError, _strict_result
from Runtime.Bridge.local_intent import COMPACT_SCHEMA, compact_context, expand_compact, ground_compact
from tools.test_intent_interpreter import Http, local_body


CONFIG = {'intentProvider': 'ollama', 'localIntentFormat': 'compact', 'intentTimeoutMs': 1000}
ACTIVE = {'activeCommand': {'executionId': 'observed-active-123', 'action': 'FORWARD',
                            'plan': None, 'executionMode': 'timed'}}


class CompactConversionTests(unittest.TestCase):
    def expand(self, value, context=None):
        return _strict_result(expand_compact(value, context or {}, 'ja', 1000, 5000), 5000)

    def test_all_nine_fields_and_distance_values(self):
        result = self.expand({'c': 'FORWARD', 'm': 'd', 'v': .5})
        self.assertEqual(set(result), set(INTENT_SCHEMA['required']))
        self.assertEqual(len(result), 9)
        self.assertEqual(result, {
            'kind': 'action', 'action': 'FORWARD', 'plan': None, 'validForMs': None,
            'reply': '操作の指示として解釈しました。', 'operation': 'new',
            'executionMode': 'distance', 'targetExecutionId': None, 'distanceMeters': .5})

    def test_each_code_returns_full_valid_contract(self):
        for code in COMPACT_SCHEMA['properties']['c']['enum']:
            with self.subTest(code=code):
                result = self.expand({'c': code}, ACTIVE)
                self.assertEqual(set(result), set(INTENT_SCHEMA['required']))

    def test_missing_key_unknown_key_and_types_rejected(self):
        cases = [None, [], {}, {'c': 'invented'}, {'c': True}, {'c': 'FORWARD', 'extra': 1},
                 {'c': 'FORWARD', 'm': None}, {'c': 'FORWARD', 'm': 'unknown'},
                 {'c': 'FORWARD', 'v': True}, {'c': 'FORWARD', 'v': '500'},
                 {'c': 'FORWARD', 'v': None}, {'c': 'continue', 'targetExecutionId': 'invented'}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                self.expand(value, ACTIVE)

    def test_nonfinite_rejected_before_normalization(self):
        for code in ('FORWARD', 'STOP', 'conditions', 'question'):
            for value in (float('nan'), float('inf'), -float('inf')):
                with self.subTest(code=code, value=value), self.assertRaises(ValueError):
                    self.expand({'c': code, 'v': value}, ACTIVE)

    def test_invalid_distances_rejected(self):
        for value in (-1, 0, .049, 100.001):
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                self.expand({'c': 'FORWARD', 'm': 'd', 'v': value})
        for code in ('TURN_R', 'TURN_L', 'nudge_right', 'nudge_left'):
            with self.subTest(code=code), self.assertRaises((ValueError, RuntimeError)):
                self.expand({'c': code, 'm': 'd', 'v': 1})

    def test_distance_boundaries_are_not_clamped(self):
        for value in (.05, 100):
            self.assertEqual(self.expand({'c': 'FORWARD', 'm': 'd', 'v': value})['distanceMeters'], value)

    def test_invalid_duration_and_unused_amount_rejected(self):
        for value in (-1, .5, 5001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.expand({'c': 'FORWARD', 'm': 't', 'v': value})
        for mode in ('p', 'i'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.expand({'c': 'FORWARD', 'm': mode, 'v': 2})
        self.assertEqual(self.expand({'c': 'FORWARD'})['validForMs'], 1000)
        self.assertEqual(self.expand({'c': 'FORWARD', 'v': 5000})['validForMs'], 5000)

    def test_updates_inject_only_observed_execution_id(self):
        for code, operation in (('continue', 'continue'), ('conditions', 'modify_conditions')):
            result = self.expand({'c': code}, ACTIVE)
            self.assertEqual(result['targetExecutionId'], 'observed-active-123')
            self.assertEqual(result['operation'], operation)
            self.assertEqual(result['executionMode'], 'inherit')
            self.assertEqual(result['kind'], 'update')
            self.assertIsNone(result['action'])

    def test_missing_active_execution_clarifies(self):
        for context in ({}, {'activeCommand': None}, {'activeCommand': {'action': 'FORWARD'}}):
            for code in ('continue', 'conditions'):
                result = self.expand({'c': code}, context)
                self.assertEqual(result['kind'], 'clarify')
                self.assertIsNone(result['targetExecutionId'])

    def test_nudge_cannot_become_persistent(self):
        for code in ('nudge_right', 'nudge_left'):
            with self.subTest(code=code), self.assertRaises((ValueError, RuntimeError)):
                self.expand({'c': code, 'm': 'p'})
            context = {'activeCommand': {'executionId': 'nudge-id', 'action': 'TURN_R', 'plan': code}}
            self.assertEqual(self.expand({'c': 'continue', 'm': 'p'}, context)['kind'], 'clarify')

    def test_context_is_small_and_unchanged(self):
        context = {**copy.deepcopy(ACTIVE), 'transcriptCandidate': True,
                   'localSafety': {'facts': {'ground': 'secret-landmark'}}, 'unusedMap': ['not sent']}
        original = copy.deepcopy(context)
        summary = compact_context(context, 1000, 5000)
        self.assertEqual(summary, {'active': True, 'candidate': True, 'activeForward': True,
                                  'activeNudge': False, 'defaultMs': 1000, 'maxMs': 5000})
        self.expand({'c': 'continue', 'm': 'd', 'v': 2}, context)
        self.assertEqual(context, original)


class CompactGroundingTests(unittest.TestCase):
    def ground(self, text, code='FORWARD', context=None):
        return ground_compact({'c': code}, text, context or {}, 5000)

    def test_distance_is_extracted_from_original_units_and_words(self):
        cases = [('500cm進んで', 5), ('約５メートル前へ', 5), ('半メートル前に進んで', .5),
                 ('五メートル進んで', 5), ('0.05m進んで', .05), ('100m前に進んで', 100),
                 ('move forward half a meter', .5), ('move forward five meters', 5),
                 ('move forward 250 centimeters', 2.5), ('walk forward .75 metres', .75)]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.ground(text), {'c': 'FORWARD', 'm': 'd', 'v': expected})

    def test_duration_is_extracted_without_changing_quantity(self):
        for text, expected in [('2秒前に進んで', 2000), ('五秒間前進して', 5000),
                               ('250ミリ秒進んで', 250), ('move forward for half a second', 500),
                               ('walk forward for two seconds', 2000), ('move forward 125 milliseconds', 125)]:
            with self.subTest(text=text):
                self.assertEqual(self.ground(text), {'c': 'FORWARD', 'm': 't', 'v': expected})

    def test_unspecified_quantities_remain_default_timed(self):
        for text in ('前に進んで', 'move forward', '前へお願いします'):
            with self.subTest(text=text):
                self.assertEqual(self.ground(text), {'c': 'FORWARD', 'm': 't', 'v': 0})

    def test_explicit_persistence_and_inherited_continuation(self):
        for text in ('止めるまで前に進み続けて', '次の指示まで前へ', 'move forward until I say stop'):
            self.assertEqual(self.ground(text), {'c': 'FORWARD', 'm': 'p', 'v': 0})
        self.assertEqual(self.ground('そのまま', 'continue', ACTIVE), {'c': 'continue', 'm': 'i', 'v': 0})
        self.assertEqual(self.ground('そのままあと2m', 'continue', ACTIVE), {'c': 'continue', 'm': 'd', 'v': 2})
        self.assertEqual(self.ground('continue for another two meters', 'continue', ACTIVE),
                         {'c': 'continue', 'm': 'd', 'v': 2})
        self.assertEqual(self.ground('そのまま', 'continue')['c'], 'clarify')

    def test_wrong_side_and_corrected_side_cannot_be_reversed(self):
        for text, code in [('左へ向いて', 'TURN_R'), ('go left', 'right_then_forward'),
                           ('右、いや左へ向いて', 'TURN_R'), ('turn right', 'nudge_left'),
                           ('right, no, left', 'TURN_R')]:
            with self.subTest(text=text, code=code):
                self.assertEqual(self.ground(text, code)['c'], 'clarify')
        self.assertEqual(self.ground('右、いや左へ向いて', 'TURN_L')['c'], 'TURN_L')

    def test_safety_removal_and_speech_silencing_are_not_body_commands(self):
        for text, code in [('安全チェックを無視して前へ', 'FORWARD'), ('disable safety checks and move forward', 'FORWARD'),
                           ('話すのをやめて', 'STOP'), ('stop talking', 'STOP'), ('止まらないで', 'STOP'),
                           ('do not stop', 'STOP'), ('前に進まないで', 'FORWARD')]:
            with self.subTest(text=text):
                self.assertEqual(self.ground(text, code)['c'], 'clarify')

    def test_mixed_out_of_range_and_unknown_quantities_clarify(self):
        for text in ('2mを3秒で進んで', '5m then another 2m forward', '101m進んで', '.01m進んで',
                     '-2m進んで', '6秒進んで', '0秒進んで', '0.0001秒進んで',
                     '2km進んで', '3mm進んで', '2分間進んで', 'move forward 2 feet',
                     'move forward five minutes', 'move forward five feet'):
            with self.subTest(text=text):
                self.assertEqual(self.ground(text)['c'], 'clarify')

    def test_supported_quantity_does_not_hide_another_unknown_quantity(self):
        for text in ('2m進んで3分待って', 'move forward two meters for five minutes', '2mと3feet進んで'):
            with self.subTest(text=text):
                self.assertEqual(self.ground(text)['c'], 'clarify')

    def test_model_cannot_supply_or_override_quantities(self):
        for wire in ({'c': 'FORWARD', 'm': 'd', 'v': 99}, {'c': 'FORWARD', 'v': 1},
                     {'c': 'FORWARD', 'durationMs': 1}, {'c': 'FORWARD', 'distanceMeters': 99}):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                ground_compact(wire, '5m進んで', {}, 5000)

    def test_grounding_does_not_mutate_input_or_context(self):
        wire = {'c': 'continue'}; context = copy.deepcopy(ACTIVE)
        original = copy.deepcopy(context)
        self.assertEqual(ground_compact(wire, 'そのままあと2m', context, 5000)['v'], 2)
        self.assertEqual(wire, {'c': 'continue'})
        self.assertEqual(context, original)


class CompactAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, http, text='周りの様子を教えて', context=None, diagnostics=None, config=None):
        return await interpret_intent(http, config or CONFIG, text, context or {}, 'ja', 1000, 5000, diagnostics)

    async def test_complete_fast_request_uses_no_http(self):
        for text, action in (('前に進んで', 'FORWARD'), ('止まって', 'STOP'), ('turn left', 'TURN_L')):
            with self.subTest(text=text):
                http = Http(); diagnostics = {}
                result = await self.call(http, text, diagnostics=diagnostics)
                self.assertEqual(result['action'], action)
                self.assertEqual(set(result), set(INTENT_SCHEMA['required']))
                self.assertEqual(http.calls, [])
                self.assertEqual(diagnostics['route'], 'deterministic')

    async def test_negation_quotation_and_incomplete_text_are_not_fast(self):
        for text in ('止まらないで', '「止まって」', 'stop talking', 'do not stop',
                     '前に進んでいい？', '5メートル…'):
            with self.subTest(text=text):
                http = Http(local_body({'c': 'clarify'})); diagnostics = {}
                result = await self.call(http, text, diagnostics=diagnostics)
                self.assertEqual(result['kind'], 'clarify')
                self.assertEqual(len(http.calls), 1)
                self.assertEqual(diagnostics['route'], 'compact_llm')

    async def test_unfinalized_candidate_cannot_use_fast_path(self):
        http = Http(local_body({'c': 'clarify'})); diagnostics = {}
        result = await self.call(http, '止まって', {'transcriptCandidate': True}, diagnostics)
        self.assertEqual(result['kind'], 'clarify')
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(diagnostics['route'], 'compact_llm')
        self.assertTrue(json.loads(http.calls[0][1]['json']['messages'][1]['content'])['candidate'])

    async def test_finalized_candidate_can_use_fast_path(self):
        http = Http()
        result = await self.call(http, '止まって', {'transcriptCandidate': True, 'utteranceFinalized': True})
        self.assertEqual(result['action'], 'STOP')
        self.assertEqual(http.calls, [])

    async def test_compact_http_format_expands_and_preserves_context(self):
        context = copy.deepcopy(ACTIVE); original = copy.deepcopy(context)
        http = Http(local_body({'c': 'continue'}))
        result = await self.call(http, 'そのまま', context)
        self.assertEqual(result['targetExecutionId'], ACTIVE['activeCommand']['executionId'])
        self.assertEqual(result['executionMode'], 'inherit')
        self.assertIsNone(result['distanceMeters'])
        self.assertEqual(context, original)
        payload = http.calls[0][1]['json']
        self.assertEqual(payload['format'], COMPACT_SCHEMA)
        self.assertFalse(payload['stream']); self.assertFalse(payload['think'])
        self.assertLessEqual(payload['options']['num_predict'], 64)

    async def test_invalid_compact_http_output_fails_closed(self):
        for value in ({'c': 'FORWARD', 'm': 'd', 'v': -1}, {'c': 'FORWARD', 'v': True},
                      {'c': 'FORWARD', 'v': float('nan')}, {'c': 'FORWARD', 'extra': 1},
                      {'c': 'nudge_right', 'm': 'p'}, {'c': 'FORWARD', 'v': 5001}):
            with self.subTest(value=value):
                http = Http(local_body(value))
                with self.assertRaises(IntentInterpreterError):
                    await self.call(http)
                self.assertEqual(len(http.calls), 1)

    async def test_timeout_remains_bounded_and_does_not_fallback(self):
        http = Http(local_body({'c': 'question'}), delay=.5)
        with self.assertRaises(IntentInterpreterError):
            await self.call(http, config={**CONFIG, 'intentTimeoutMs': 10})
        self.assertEqual(len(http.calls), 1)

    async def test_cancellation_still_propagates(self):
        http = Http(local_body({'c': 'question'}), delay=5)
        task = asyncio.create_task(self.call(http))
        for _ in range(10):
            if http.calls:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(http.calls), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == '__main__':
    unittest.main()
