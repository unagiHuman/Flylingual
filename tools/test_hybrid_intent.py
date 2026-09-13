"""Offline classifier orchestration tests, no Brain or audio integration."""
import asyncio
import unittest
from unittest.mock import patch
from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError
from Runtime.Bridge.local_intent import expand_compact


class HybridTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, text='右側に寄って進んで', *, context=None, code='clarify', fail=None, remote='right_then_forward', timeout=1000):
        calls = []
        async def once(http, config, text, context, language, default_ms, max_ms, diagnostics):
            calls.append(config)
            if len(calls) == 1:
                diagnostics['compactResult'] = {'c': code}
                return expand_compact({'c': code}, context, language, default_ms, max_ms)
            if fail:
                raise fail
            return expand_compact({'c': remote}, context, language, default_ms, max_ms)
        diagnostics = {}
        with patch('Runtime.Bridge.intent_interpreter._interpret_once', side_effect=once):
            result = await interpret_intent(None, {'intentProvider': 'llama_cpp', 'intentModel': 'configured',
                'localIntentResponsesFallback': True, 'intentTimeoutMs': timeout}, text,
                context or {}, 'ja', 1000, 5000, diagnostics)
        return result, calls, diagnostics

    async def test_explicit_reinterpretation(self):
        result, calls, diagnostics = await self.run_case()
        self.assertEqual(result['plan'], 'right_then_forward')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['intentProvider'], 'responses')
        self.assertLessEqual(calls[1]['intentTimeoutMs'], 1000)
        self.assertEqual(diagnostics['route'], 'responses_reinterpretation')

    async def test_ambiguous_negated_and_unfinished_stay_local(self):
        for text in ('そっちへ行って', '右には行かないで', '右か左へ', '砂糖まで前へ', 'あそこまで進んで'):
            result, calls, _ = await self.run_case(text)
            self.assertEqual(len(calls), 1, text)
            self.assertEqual(result['kind'], 'clarify')
        _, calls, _ = await self.run_case(context={'transcriptCandidate': True, 'utteranceFinalized': False})
        self.assertEqual(len(calls), 1)

    async def test_success_and_question_do_not_escalate(self):
        for code in ('TURN_R', 'question', 'STOP'):
            _, calls, _ = await self.run_case(code=code)
            self.assertEqual(len(calls), 1)

    async def test_cloud_failure_keeps_clarification(self):
        for failure in (IntentInterpreterError('api_key_missing'), asyncio.TimeoutError()):
            result, _, diagnostics = await self.run_case(fail=failure)
            self.assertEqual(result['kind'], 'clarify')
            self.assertEqual(diagnostics['fallbackOutcome'], 'unavailable')

    async def test_cancellation_propagates(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.run_case(fail=asyncio.CancelledError())

    async def test_remote_can_still_clarify(self):
        result, _, _ = await self.run_case(remote='clarify')
        self.assertEqual(result['kind'], 'clarify')

    async def test_does_not_add_forward_to_small_turn(self):
        result, _, diagnostics = await self.run_case('もうちょっと右行って')
        self.assertEqual(result['kind'], 'clarify')
        self.assertEqual(diagnostics['fallbackOutcome'], 'unsupported_direction')

    async def test_local_failure_does_not_contact_cloud(self):
        with patch('Runtime.Bridge.intent_interpreter._interpret_once', side_effect=IntentInterpreterError('intent_translation_failed')) as once:
            with self.assertRaises(IntentInterpreterError):
                await interpret_intent(None, {'localIntentResponsesFallback': True, 'intentProvider': 'llama_cpp'},
                                       '右へ', {}, 'ja', 1000, 5000)
            once.assert_awaited_once()

    async def test_common_deadline_cancels_remote(self):
        calls = []
        async def once(http, config, text, context, language, default_ms, max_ms, diagnostics):
            calls.append(config)
            if len(calls) == 1:
                diagnostics['compactResult'] = {'c': 'clarify'}
                await asyncio.sleep(.02)
                return expand_compact({'c': 'clarify'}, context, language, default_ms, max_ms)
            await asyncio.sleep(1)
        with patch('Runtime.Bridge.intent_interpreter._interpret_once', side_effect=once):
            result = await asyncio.wait_for(interpret_intent(None, {'localIntentResponsesFallback': True,
                'intentProvider': 'llama_cpp', 'intentTimeoutMs': 70}, '右へ進んで', {}, 'ja', 1000, 5000), .5)
        self.assertEqual(result['kind'], 'clarify')
        self.assertLess(calls[1]['intentTimeoutMs'], 70)

    async def test_default_does_not_escalate(self):
        with patch('Runtime.Bridge.intent_interpreter._interpret_once') as once:
            once.return_value = {'kind': 'clarify'}
            await interpret_intent(None, {}, '右へ', {}, 'ja', 1000, 5000)
            once.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
