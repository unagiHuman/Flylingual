"""Offline intent-provider boundary tests; no Unity/Brain or live service substitute."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from Runtime.Bridge.intent_contract import INTENT_SCHEMA
from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError, local_intent_endpoint


GOOD = {'kind': 'action', 'action': 'FORWARD', 'plan': None, 'validForMs': None,
        'reply': '進むね。', 'operation': 'new', 'executionMode': 'distance',
        'targetExecutionId': None, 'distanceMeters': 5}


class Reply:
    def __init__(self, body, status=200, delay=0):
        self.body, self.status, self.delay = body, status, delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.body


class Http:
    def __init__(self, body=None, status=200, delay=0):
        self.reply = Reply(body, status, delay)
        self.calls = []
        self.headers = {}

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.reply


def local_body(result=GOOD):
    return {'done': True, 'done_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(result)},
            'total_duration': 123456, 'eval_count': 24}


class IntentInterpreterTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, http, config=None, diagnostics=None):
        return await interpret_intent(http, {'localIntentFormat': 'full', **(config or {'intentProvider': 'ollama'})},
                                      '約5メートル前へ', {'activeCommand': None}, 'ja', 1000, 5000, diagnostics)

    async def test_local_without_key_and_exact_contract(self):
        http = Http(local_body())
        diagnostics = {}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(await self.call(http, diagnostics=diagnostics), GOOD)
        url, kwargs = http.calls[0]
        self.assertEqual(url, 'http://127.0.0.1:11435/api/chat')
        self.assertNotIn('headers', kwargs)
        self.assertIsNone(kwargs['auth'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['json']['format'], INTENT_SCHEMA)
        self.assertEqual(kwargs['json']['options'], {'temperature': 0, 'num_ctx': 8192, 'num_predict': 600})
        self.assertFalse(kwargs['json']['think'])
        self.assertFalse(kwargs['json']['stream'])
        self.assertEqual(set(diagnostics), {'provider', 'model', 'route', 'latencyMs', 'total_duration', 'eval_count'})

    async def test_default_responses_payload(self):
        http = Http({'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': json.dumps(GOOD)}]}]})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-placeholder'}):
            self.assertEqual(await self.call(http, {'intentModel': 'configured-model'}), GOOD)
        url, kwargs = http.calls[0]
        self.assertEqual(url, 'https://api.openai.com/v1/responses')
        self.assertEqual(kwargs['json']['model'], 'configured-model')
        self.assertFalse(kwargs['json']['store'])
        self.assertEqual(kwargs['json']['text']['format']['schema'], INTENT_SCHEMA)
        self.assertEqual(kwargs['json']['max_output_tokens'], 600)

    async def test_question_and_update_keep_existing_semantics(self):
        question = {**GOOD, 'kind': 'question', 'action': None, 'executionMode': 'timed',
                    'validForMs': 1000, 'distanceMeters': None}
        update = {**GOOD, 'kind': 'update', 'action': None, 'operation': 'continue',
                  'targetExecutionId': 'active-1', 'distanceMeters': 2}
        for result in (question, update):
            self.assertEqual(await self.call(Http(local_body(result))), result)

    async def test_responses_requires_key_no_request(self):
        http = Http()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(IntentInterpreterError, '^api_key_missing$'):
                await self.call(http, {'intentModel': 'configured-model'})
        self.assertEqual(http.calls, [])

    async def test_rejects_schema_and_semantic_failures(self):
        cases = []
        for key, value in [('distanceMeters', True), ('validForMs', True), ('reply', 123),
                           ('distanceMeters', float('nan')), ('distanceMeters', float('inf')),
                           ('distanceMeters', 101), ('action', 'FLY'), ('targetExecutionId', []),
                           ('executionMode', 'timed'), ('operation', 'continue')]:
            item = dict(GOOD); item[key] = value; cases.append(item)
        cases.extend([{'kind': 'question'}, {**GOOD, 'motor': 1}, [], None])
        for value in cases:
            with self.subTest(value=value):
                http = Http(local_body(value))
                with self.assertRaises(IntentInterpreterError):
                    await self.call(http)
                self.assertEqual(len(http.calls), 1)

    async def test_refuses_fenced_duplicate_or_incomplete_output(self):
        bodies = [None, [], {'done': False}, {**local_body(), 'done_reason': 'length'}]
        for text in ('```json\n{}\n```', '{"kind":"action","kind":"question"}', 'not json'):
            body = local_body(); body['message']['content'] = text; bodies.append(body)
        body = local_body(); body['message']['tool_calls'] = [{'function': {}}]; bodies.append(body)
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(IntentInterpreterError):
                    await self.call(Http(body))

    async def test_timeout_and_redirect_never_fallback(self):
        for http in (Http(local_body(), status=302), Http(local_body(), status=500), Http(local_body(), delay=.2)):
            with self.assertRaises(IntentInterpreterError):
                await self.call(http, {'intentProvider': 'ollama', 'intentTimeoutMs': 10})
            self.assertEqual(len(http.calls), 1)
            self.assertFalse(http.calls[0][1]['allow_redirects'])

    async def test_cancellation_propagates(self):
        task = asyncio.create_task(self.call(Http(local_body(), delay=1)))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_inherited_credentials_and_proxy_rejected(self):
        for attribute, value in [('headers', {'Authorization': 'placeholder'}), ('_default_auth', object()), ('trust_env', True)]:
            http = Http(local_body()); setattr(http, attribute, value)
            with self.assertRaises(IntentInterpreterError):
                await self.call(http)
            self.assertEqual(http.calls, [])

    async def test_conversation_gate_remains(self):
        from Runtime.Bridge.conversation import ConversationAdapter, ConversationError
        adapter = ConversationAdapter.__new__(ConversationAdapter)
        adapter.state = 'off'; adapter.http = Http(local_body())
        with self.assertRaisesRegex(ConversationError, '^conversation_not_started$'):
            await adapter.interpret('前へ', {}, 1000, 5000)
        self.assertEqual(adapter.http.calls, [])

    async def test_invalid_provider_or_model_never_sends(self):
        for config in ({'intentProvider': 'unknown'}, {'intentProvider': 'ollama', 'localIntentModel': ''},
                       {'intentProvider': 'ollama', 'intentTimeoutMs': True}):
            http = Http(local_body())
            with self.assertRaises(IntentInterpreterError):
                await self.call(http, config)
            self.assertEqual(http.calls, [])

    def test_loopback_only_urls(self):
        for url in ('http://127.0.0.1:11435', 'http://localhost:11435/', 'http://[::1]:11435'):
            self.assertTrue(local_intent_endpoint(url).endswith('/api/chat'))
        for url in ('https://127.0.0.1:11435', 'http://example.com', 'http://192.168.1.1',
                    'http://127.0.0.1@evil.test', 'http://user:password@localhost',
                    'http://localhost/api/chat', 'http://localhost?x=1', 'http://localhost#x',
                    'http://localhost:0', 'http://localhost:99999', 'http://127.1', ' http://localhost'):
            with self.subTest(url=url), self.assertRaises(IntentInterpreterError):
                local_intent_endpoint(url)


if __name__ == '__main__':
    unittest.main()
