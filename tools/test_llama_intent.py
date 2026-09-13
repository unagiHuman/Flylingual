"""Offline native llama transport boundaries, never real-model or Brain tests."""
import asyncio
import json
import unittest

from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError
from Runtime.Bridge.intent_labels import LABEL_GBNF
from Runtime.Bridge.intent_contract import INTENT_SCHEMA
from Runtime.Bridge.local_intent import COMPACT_SCHEMA
from tools.test_intent_interpreter import Reply


CONFIG = {'intentProvider': 'llama_cpp', 'localIntentFormat': 'label',
          'localIntentUrl': 'http://127.0.0.1:11436', 'intentTimeoutMs': 1000,
          'localIntentCachePrompt': True}


class NativeHttp:
    def __init__(self, outputs=None, cache_n=100, delay=0, reject_at=None):
        self.outputs = list(outputs or ['Q'])
        self.cache_n, self.delay, self.reject_at = cache_n, delay, reject_at
        self.headers = {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = kwargs['json']
        if url.endswith('/apply-template'):
            messages = payload['messages']
            body = {'prompt': 'SYSTEM\n' + messages[0]['content'] + '\nUSER\n' + messages[-1]['content'] + '\nASSISTANT\n'}
        elif payload['n_predict'] == 0:
            body = {'stop': True}
        else:
            output = self.outputs.pop(0)
            body = output if isinstance(output, dict) else {
                'stop': True, 'stop_type': 'eos', 'truncated': False, 'content': output,
                'timings': {'cache_n': self.cache_n}, 'tokens_evaluated': 10, 'tokens_predicted': 1}
        return Reply(body, status=302 if len(self.calls) == self.reject_at else 200, delay=self.delay)

    def completions(self, prefill=False):
        return [kwargs['json'] for url, kwargs in self.calls if url.endswith('/completion')
                and (kwargs['json']['n_predict'] == 0) == prefill]


class LlamaIntentTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, http, text='周りについて教えて', config=None):
        return await interpret_intent(http, config or CONFIG, text, {}, 'ja', 1000, 5000)

    async def test_raw_label_is_restored_and_grammar_sent(self):
        http = NativeHttp(['Q'])
        result = await self.call(http)
        self.assertEqual(result['kind'], 'question')
        self.assertEqual(set(result), set(INTENT_SCHEMA['required']))
        completion = http.completions()[0]
        self.assertEqual(completion['grammar'], LABEL_GBNF)
        self.assertNotIn('json_schema', completion)
        self.assertFalse(completion['stream'])
        self.assertEqual(completion['id_slot'], 0)

    async def test_partial_extra_quoted_or_unknown_labels_rejected(self):
        for output in ('', ' Q', 'Q\n', 'CON', 'Q because question', '"Q"', 'UNKNOWN'):
            with self.subTest(output=output), self.assertRaises(IntentInterpreterError):
                await self.call(NativeHttp([output]))

    async def test_limit_or_truncated_output_rejected_even_if_label_looks_valid(self):
        for body in ({'stop': True, 'stop_type': 'limit', 'content': 'Q'},
                     {'stop': True, 'stop_type': 'eos', 'content': 'Q', 'truncated': True},
                     {'stop': False, 'stop_type': 'eos', 'content': 'Q'}):
            with self.subTest(body=body), self.assertRaises(IntentInterpreterError):
                await self.call(NativeHttp([body]))

    async def test_cache_disabled_never_prefills(self):
        http = NativeHttp(['Q'])
        await self.call(http, config={**CONFIG, 'localIntentCachePrompt': False})
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(http.completions(prefill=True), [])
        self.assertFalse(http.completions()[0]['cache_prompt'])

    async def test_cache_warms_once_but_each_utterance_gets_new_completion(self):
        http = NativeHttp(['Q', 'C'])
        first = await self.call(http, '今の周りについて教えて')
        second = await self.call(http, 'どこへ行けばよいかわからない')
        self.assertEqual(first['kind'], 'question')
        self.assertEqual(second['kind'], 'clarify')
        self.assertEqual(len(http.completions(prefill=True)), 1)
        self.assertEqual(len(http.completions()), 2)
        self.assertIn('今の周りについて教えて', http.completions()[0]['prompt'])
        self.assertIn('どこへ行けばよいかわからない', http.completions()[1]['prompt'])
        self.assertNotIn('今の周りについて教えて', http.completions(prefill=True)[0]['prompt'])

    async def test_zero_cache_hit_allows_next_request_to_rewarm(self):
        http = NativeHttp(['Q', 'Q'], cache_n=0)
        await self.call(http)
        await self.call(http)
        self.assertEqual(len(http.completions(prefill=True)), 2)
        self.assertEqual(len(http.completions()), 2)

    async def test_native_compact_json_restores_full_proposal(self):
        http = NativeHttp([json.dumps({'c': 'FORWARD'})])
        result = await self.call(http, 'move forward about five meters',
                                 config={**CONFIG, 'localIntentFormat': 'compact'})
        self.assertEqual(result['action'], 'FORWARD')
        self.assertEqual(result['distanceMeters'], 5)
        self.assertEqual(set(result), set(INTENT_SCHEMA['required']))
        self.assertEqual(http.completions()[0]['json_schema'], COMPACT_SCHEMA)
        self.assertNotIn('grammar', http.completions()[0])

    async def test_only_loopback_origins_allowed(self):
        for url in ('http://localhost:11436', 'http://[::1]:11436'):
            http = NativeHttp()
            await self.call(http, config={**CONFIG, 'localIntentUrl': url})
            self.assertTrue(all(target.startswith(url + '/') for target, _ in http.calls))
        for url in ('http://example.com:11436', 'http://192.168.1.1:11436',
                    'https://localhost:11436', 'http://user:secret@localhost:11436'):
            http = NativeHttp()
            with self.subTest(url=url), self.assertRaises(IntentInterpreterError):
                await self.call(http, config={**CONFIG, 'localIntentUrl': url})
            self.assertEqual(http.calls, [])

    async def test_authentication_and_environment_proxy_are_rejected(self):
        for attribute, value in [('headers', {'Authorization': 'placeholder'}),
                                 ('_default_auth', object()), ('trust_env', True)]:
            http = NativeHttp(); setattr(http, attribute, value)
            with self.assertRaises(IntentInterpreterError):
                await self.call(http)
            self.assertEqual(http.calls, [])

    async def test_redirect_at_each_stage_fails_without_followup(self):
        for stage in (1, 2, 3):
            http = NativeHttp(reject_at=stage)
            with self.subTest(stage=stage), self.assertRaises(IntentInterpreterError):
                await self.call(http)
            self.assertEqual(len(http.calls), stage)
            for _, kwargs in http.calls:
                self.assertFalse(kwargs['allow_redirects'])
                self.assertIsNone(kwargs['auth'])
                self.assertIsNone(kwargs['proxy'])
                self.assertNotIn('headers', kwargs)

    async def test_timeout_is_total_across_template_prefill_and_completion(self):
        # Each individual response fits 100 ms, but all three cannot fit together.
        http = NativeHttp(delay=.045)
        with self.assertRaises(IntentInterpreterError):
            await self.call(http, config={**CONFIG, 'intentTimeoutMs': 100})
        self.assertGreaterEqual(len(http.calls), 2)
        self.assertLessEqual(len(http.calls), 3)

    async def test_cancellation_interrupts_multirequest_operation(self):
        http = NativeHttp(delay=.1)
        task = asyncio.create_task(self.call(http))
        while len(http.calls) < 2 and not task.done():
            await asyncio.sleep(.005)
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(http.calls), 2)


if __name__ == '__main__':
    unittest.main()
