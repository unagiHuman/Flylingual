"""Network-free Live protocol regressions; no Brain or microphone acceptance."""
import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationAdapter


class EventSocket:
    """Deliver protocol events through the production reader, without sockets."""
    def __init__(self):
        self.closed = False
        self.events = asyncio.Queue()
        self.pending = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.pending:
            self.events.task_done()
            self.pending = False
        event = await self.events.get()
        self.pending = True
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(event))

    async def send_json(self, event):
        if event['type'] == 'session.start':
            self.events.put_nowait({'type': 'session.started', 'session': {}})

    async def close(self):
        self.closed = True

    async def feed(self, *events):
        for event in events:
            self.events.put_nowait(event)
        await asyncio.wait_for(self.events.join(), timeout=1)


def transcript(start, end, text):
    return {'type': 'session.input_transcript.delta', 'start_ms': start,
            'end_ms': end, 'delta': text}


def delegation(offset, identifier):
    return {'type': 'session.delegation.created', 'offset_ms': offset,
            'delegation': {'id': identifier, 'target': 'client'}}


class LiveSessionClockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config = copy.deepcopy(_DEFAULT['conversation'])
        config['mode'] = 'live'
        self.utterance = AsyncMock()
        self.adapter = ConversationAdapter(config, AsyncMock(), self.utterance)
        # Disable only audio pacing; the production start, stop and reader run.
        self.adapter._send_audio = AsyncMock()
        self.factory_patch = patch('Runtime.Bridge.conversation.aiohttp.ClientSession')
        self.factory = self.factory_patch.start()
        self.key_patch = patch.dict('os.environ', {'OPENAI_API_KEY': 'protocol-test-placeholder'})
        self.key_patch.start()

    async def asyncTearDown(self):
        await self.adapter.stop(graceful=False)
        self.key_patch.stop()
        self.factory_patch.stop()

    async def connect(self, interaction='control'):
        socket = EventSocket()
        http = SimpleNamespace(ws_connect=AsyncMock(return_value=socket), close=AsyncMock())
        self.factory.return_value = http
        self.adapter.interaction = interaction
        await self.adapter.start()
        return socket

    async def test_chat_to_new_control_connection_accepts_zero_based_transcript(self):
        old = await self.connect('chat_only')
        await old.feed(transcript(12000, 13000, 'old chat'), delegation(13000, 'same-id'))
        self.assertEqual(self.adapter.max_offset, 13000)
        old_generation = self.adapter.context_generation
        await self.adapter.stop(graceful=False)
        self.utterance.reset_mock()

        new = await self.connect()
        self.assertIsNot(old, new)
        self.assertTrue(old.closed)
        self.assertGreater(self.adapter.context_generation, old_generation)
        self.assertEqual((self.adapter.last_offset, self.adapter.max_offset), (-1, -1))
        self.assertFalse(self.adapter.fragments)
        self.assertFalse(self.adapter.delegations)
        # Reusing an opaque ID across independent sessions must not suppress it.
        await new.feed(transcript(0, 200, 'forward'), delegation(200, 'same-id'))
        self.utterance.assert_awaited_once_with('forward', 'same-id', self.adapter.context_generation)
        self.assertEqual(self.adapter.diagnostics()['delegationWithTranscript'], 1)
        self.assertEqual(self.adapter.diagnostics()['delegationWithoutTranscript'], 0)

    async def test_same_connection_context_clear_preserves_old_audio_boundary(self):
        socket = await self.connect()
        await socket.feed(transcript(100, 500, 'old request'), delegation(500, 'used-id'))
        self.utterance.reset_mock()
        old_generation = self.adapter.context_generation
        self.adapter.audio_queue.put_nowait(b'old audio')
        self.adapter.clear_context()
        self.assertEqual(self.adapter.context_generation, old_generation + 1)
        self.assertEqual((self.adapter.last_offset, self.adapter.max_offset), (500, 500))
        self.assertFalse(self.adapter.fragments)
        self.assertTrue(self.adapter.audio_queue.empty())
        self.assertIn('used-id', self.adapter.delegations)
        # Late old audio and an already-used delegation remain rejected.
        await socket.feed(transcript(100, 500, 'late old request'),
                          delegation(500, 'late-id'), delegation(500, 'used-id'))
        self.utterance.assert_not_awaited()
        await socket.feed(transcript(501, 700, 'new request'), delegation(700, 'new-id'))
        self.utterance.assert_awaited_once_with('new request', 'new-id', self.adapter.context_generation)
        self.assertEqual(self.adapter.diagnostics()['delegationRejectedDuplicate'], 1)

    async def test_repeated_start_of_live_connection_keeps_cursor_and_deduplication(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 200, 'forward'), delegation(200, 'used-id'))
        self.utterance.reset_mock()
        generation = self.adapter.context_generation
        await self.adapter.start()
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(self.adapter.context_generation, generation)
        self.assertEqual((self.adapter.last_offset, self.adapter.max_offset), (200, 200))
        await socket.feed(delegation(200, 'used-id'))
        self.utterance.assert_not_awaited()
        self.assertEqual(self.adapter.diagnostics()['delegationRejectedDuplicate'], 1)


if __name__ == '__main__':
    unittest.main()
