"""Real loopback HTTP transport tests; no Brain or game simulation is used."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from aiohttp import web
from Runtime.Bridge.cloud_intent import request_cloud, cloud_endpoint
from Runtime.Bridge.intent_interpreter import interpret_intent


class CloudTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.status = 200
        self.raw = json.dumps({'schemaVersion': 1, 'c': 'question', 'speech': '今は止まってるよ'}).encode()
        self.delay = 0
        self.chunked = False
        self.calls = []
        self.received = asyncio.Event()
        app = web.Application()
        app.router.add_post('/api/fly/translate', self.handle)
        self.runner = web.AppRunner(app, shutdown_timeout=.05)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.url = 'http://127.0.0.1:%s/api/fly/translate' % site._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def handle(self, request):
        self.calls.append((dict(request.headers), await request.json()))
        self.received.set()
        await asyncio.sleep(self.delay)
        if self.chunked:
            response = web.StreamResponse(status=self.status)
            await response.prepare(request)
            await response.write(self.raw[:15])
            await asyncio.sleep(.02)
            await response.write(self.raw[15:])
            await response.write_eof()
            return response
        return web.Response(status=self.status, body=self.raw)

    async def invoke(self, **overrides):
        diagnostics = {}
        config = {'cloudIntentUrl': self.url, 'intentTimeoutMs': 1000, **overrides}
        result = await request_cloud(config, '今はどんな状態？', {}, 'ja', 1000, 5000, diagnostics)
        return result, diagnostics

    async def test_chunked_response_accumulates_to_eof(self):
        self.chunked = True
        result, diagnostics = await self.invoke()
        self.assertEqual(result['kind'], 'question')
        self.assertEqual(result['reply'], '今は止まってるよ')
        self.assertEqual(diagnostics['httpStatus'], 200)

    async def test_no_credentials_and_only_semantic_payload(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-not-a-real-key',
                                     'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1'}):
            await self.invoke()
        headers, payload = self.calls[0]
        self.assertFalse({'authorization', 'proxy-authorization', 'cookie'} & {h.lower() for h in headers})
        self.assertEqual(set(payload), {'schemaVersion', 'playerInput', 'language', 'flyState'})
        self.assertNotIn('unit-test-not-a-real-key', json.dumps(payload))

    async def test_402_and_redirect_fallback_without_retry(self):
        for status in (402, 429, 500, 503, 302):
            self.status = status
            result, diagnostics = await self.invoke()
            self.assertEqual(result['kind'], 'clarify')
            self.assertEqual(diagnostics['cloudOutcome'], 'CloudUnavailable')
            self.assertEqual(diagnostics['httpStatus'], status)
        self.assertEqual(len(self.calls), 5)

    async def test_rate_limit_and_unavailable_leave_basic_commands_local(self):
        for status in (429, 503):
            self.status = status
            await self.invoke()
            before = len(self.calls)
            for text, action in (('前進', 'FORWARD'), ('右', 'TURN_R'), ('左', 'TURN_L'), ('停止', 'STOP'),
                                 ('forward', 'FORWARD'), ('right', 'TURN_R'), ('left', 'TURN_L'), ('stop', 'STOP')):
                diagnostics = {}
                result = await interpret_intent(None, {'intentProvider': 'vercel', 'cloudIntentUrl': self.url},
                                                text, {}, 'ja', 1000, 5000, diagnostics)
                self.assertEqual(result['action'], action)
                self.assertEqual(diagnostics['route'], 'deterministic')
            self.assertEqual(len(self.calls), before)

    async def test_observation_is_bounded_fresh_and_not_body_claim(self):
        for context, expected in (
                ({'stale': False, 'facts': {'forward': .4, 'turn': -.2, 'rawNeurons': [1, 2]}},
                 {'fresh': True, 'forward': .4, 'turn': -.2, 'bodyMovementVerified': False}),
                ({'stale': True, 'facts': {'forward': .4, 'turn': -.2}},
                 {'fresh': False, 'forward': None, 'turn': None, 'bodyMovementVerified': False}),
                ({'stale': False, 'facts': {'forward': float('nan'), 'turn': 1001}},
                 {'fresh': True, 'forward': None, 'turn': None, 'bodyMovementVerified': False}),
                ({'stale': False, 'facts': {'forward': True, 'turn': float('inf')}},
                 {'fresh': True, 'forward': None, 'turn': None, 'bodyMovementVerified': False})):
            await request_cloud({'cloudIntentUrl': self.url}, '今どう？', context, 'ja', 1000, 5000)
            state = self.calls[-1][1]['flyState']
            self.assertEqual(state['observation'], expected)
            self.assertNotIn('rawNeurons', json.dumps(state))

    async def test_oversized_and_malformed_responses_are_safe(self):
        for raw in (b'x' * 5000, b'{', b'[]',
                    b'{"schemaVersion":true,"c":"question","speech":"x"}',
                    b'{"schemaVersion":1,"c":[],"speech":"x"}',
                    b'{"schemaVersion":1,"c":"question","speech":"x","extra":1}',
                    b'{"schemaVersion":1,"c":"STOP","c":"FORWARD","speech":"x"}'):
            self.raw = raw
            result, diagnostics = await self.invoke()
            self.assertEqual(result['kind'], 'clarify', raw[:60])
            self.assertEqual(diagnostics['cloudOutcome'], 'CloudUnavailable')

    async def test_timeout_falls_back(self):
        self.delay = .2
        result, diagnostics = await self.invoke(intentTimeoutMs=20)
        self.assertEqual(result['kind'], 'clarify')
        self.assertEqual(diagnostics['cloudOutcome'], 'CloudUnavailable')

    async def test_external_cancellation_propagates(self):
        self.delay = .2
        task = asyncio.create_task(self.invoke())
        await self.received.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_fast_rule_works_without_cloud(self):
        diagnostics = {}
        with patch('Runtime.Bridge.cloud_intent.request_cloud', side_effect=AssertionError('Cloud must not be called')):
            result = await interpret_intent(None, {'intentProvider': 'vercel', 'cloudIntentUrl': self.url},
                                            '止まって', {}, 'ja', 1000, 5000, diagnostics)
        self.assertEqual(result['action'], 'STOP')
        self.assertEqual(diagnostics['route'], 'deterministic')
        self.assertEqual(self.calls, [])


class EndpointTests(unittest.TestCase):
    def test_invalid_endpoint_rejected(self):
        for value in ('http://remote.example/api/fly/translate', 'https://ai-gateway.vercel.sh/api/fly/translate',
                      'https://u:p@example.com/api/fly/translate', 'https://example.com/api/fly/translate?key=x',
                      'https://example.com/other', None):
            with self.assertRaises(ValueError):
                cloud_endpoint(value)


if __name__ == '__main__':
    unittest.main()
