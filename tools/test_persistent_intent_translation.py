"""Offline Responses boundary contracts; not semantic/API or Brain acceptance."""
import copy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationAdapter, ConversationError, INTENT_SCHEMA
from Runtime.Bridge.conversation_settings import DEFAULT_SETTINGS
from Runtime.Bridge.conversation_prompts import build_voice_instructions


def proposal(**changes):
    value = dict(kind='action', action='FORWARD', plan=None, validForMs=None,
                 reply='前に進み続ける指示だね。', operation='new',
                 executionMode='until_next_command', targetExecutionId=None)
    value.update(changes)
    return value


class PersistentIntentTranslationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']),
                                           AsyncMock(), AsyncMock())
        self.adapter.state = 'live'
        self.adapter.http = Mock()
        self.key_patch = patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-test-placeholder'})
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.observed = {'activeCommand': {
            'executionId': 'execution-current-123', 'action': 'FORWARD',
            'plan': 'right_then_forward', 'phase': 1,
            'executionMode': 'timed', 'remainingMs': 2000},
            'localSafety': {'fresh': True, 'source': 'unity_local_sensors'}}

    def response(self, value, status='completed'):
        response = Mock(status=200)
        response.json = AsyncMock(return_value={
            'status': status, 'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': json.dumps(value, ensure_ascii=False)}]}]})
        self.adapter.http.post.return_value = AsyncMock()
        self.adapter.http.post.return_value.__aenter__.return_value = response

    async def interpret(self, value, text='指示があるまでずっと前に進んで'):
        self.response(value)
        return await self.adapter.interpret(text, self.observed, 4000, 8000)

    async def test_persistent_action_keeps_null_duration(self):
        value = proposal()
        self.assertEqual(await self.interpret(value), value)

    async def test_turn_then_forward_keeps_persistent_mode(self):
        for plan in ('right_then_forward', 'left_then_forward', 'forward_until_concern'):
            with self.subTest(plan=plan):
                value = proposal(kind='plan', action=None, plan=plan)
                self.assertEqual(await self.interpret(value), value)

    async def test_updates_preserve_target_and_mode(self):
        for operation, mode, duration in (
                ('continue', 'inherit', None), ('continue', 'until_next_command', None),
                ('continue', 'timed', 8000), ('modify_conditions', 'inherit', None)):
            with self.subTest(operation=operation, mode=mode):
                value = proposal(kind='update', action=None, operation=operation,
                                 executionMode=mode, validForMs=duration,
                                 targetExecutionId='execution-current-123')
                self.assertEqual(await self.interpret(value, 'そのまま'), value)

    async def test_finite_nudge_and_stop_remain_timed(self):
        values = [proposal(kind='plan', action=None, plan='nudge_right',
                           executionMode='timed', validForMs=4000),
                  proposal(action='STOP', executionMode='timed', validForMs=4000)]
        for value in values:
            with self.subTest(action=value['action'], plan=value['plan']):
                self.assertEqual(await self.interpret(value), value)

    async def test_question_and_clarify_remain_non_operations(self):
        for kind in ('question', 'clarify'):
            value = proposal(kind=kind, action=None, executionMode='timed', validForMs=4000)
            self.assertEqual(await self.interpret(value), value)

    async def test_invalid_persistent_and_update_combinations_fail_closed(self):
        values = [proposal(action='STOP'),
                  proposal(kind='plan', action=None, plan='nudge_left'),
                  proposal(validForMs=4000),
                  proposal(kind='update', action=None, operation='continue',
                           executionMode='inherit', targetExecutionId=None),
                  proposal(kind='update', action=None, operation='modify_conditions',
                           targetExecutionId='execution-current-123'),
                  proposal(executionMode='timed', validForMs=8001),
                  proposal(kind='question', action=None)]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ConversationError, '^intent_translation_failed$'):
                    await self.interpret(value)

    async def test_request_preserves_observed_identity_and_excludes_persona(self):
        self.adapter.settings.update(persona='custom', personaText='PRIVATE_STYLE_SENTINEL')
        original = copy.deepcopy(self.observed)
        await self.interpret(proposal())
        args, kwargs = self.adapter.http.post.call_args
        self.assertEqual(args, ('https://api.openai.com/v1/responses',))
        payload = kwargs['json']
        self.assertFalse(payload['store'])
        self.assertEqual(payload['model'], self.adapter.config['intentModel'])
        self.assertEqual(json.loads(payload['input'][1]['content'])['observed'], original)
        self.assertEqual(self.observed, original)
        self.assertNotIn('PRIVATE_STYLE_SENTINEL', json.dumps(payload))
        self.assertEqual(payload['text']['format']['schema'], INTENT_SCHEMA)
        self.assertTrue(payload['text']['format']['strict'])

    async def test_incomplete_response_is_not_executed(self):
        self.response(proposal(), status='incomplete')
        with self.assertRaisesRegex(ConversationError, '^intent_translation_failed$'):
            await self.adapter.interpret('前へ', self.observed, 4000, 8000)

    async def test_live_output_requires_new_fields_even_for_timed_actions(self):
        legacy = dict(kind='action', action='FORWARD', plan=None, validForMs=4000, reply='前へ。')
        with self.assertRaisesRegex(ConversationError, '^intent_translation_failed$'):
            await self.interpret(legacy)

    async def test_mock_remains_bounded_and_uses_complete_contract(self):
        self.adapter.state = 'mock'
        result = await self.adapter.interpret('forward', self.observed, 4000, 8000)
        self.assertEqual(set(result), set(INTENT_SCHEMA['required']))
        self.assertEqual(result['operation'], 'new')
        self.assertEqual(result['executionMode'], 'timed')
        self.assertIsNone(result['targetExecutionId'])
        self.assertEqual(result['validForMs'], 4000)
        self.adapter.http.post.assert_not_called()


class PersistentIntentSchemaTests(unittest.TestCase):
    def test_every_strict_property_is_required(self):
        self.assertEqual(set(INTENT_SCHEMA['properties']), set(INTENT_SCHEMA['required']))
        self.assertFalse(INTENT_SCHEMA['additionalProperties'])
        self.assertEqual(INTENT_SCHEMA['properties']['validForMs']['type'], ['integer', 'null'])
        self.assertIn('update', INTENT_SCHEMA['properties']['kind']['enum'])

    def test_both_voice_languages_describe_continuation_delegation(self):
        for language, phrase in (('ja', 'そのまま次の指示まで'),
                                 ('en', 'Keep doing that until I say stop')):
            instructions = build_voice_instructions({**DEFAULT_SETTINGS, 'language': language})
            self.assertIn(phrase, instructions)
            self.assertIn('backend', instructions)


if __name__ == '__main__':
    unittest.main()
