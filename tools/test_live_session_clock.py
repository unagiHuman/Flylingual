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

    async def test_delegation_in_received_tail_includes_the_complete_tail(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 100, '前に'), transcript(100, 300, '進んで'),
                          delegation(150, 'tail-boundary'))
        self.utterance.assert_awaited_once_with('前に進んで', 'tail-boundary',
                                               self.adapter.context_generation)
        self.assertEqual(self.adapter.last_offset, 300)

    async def test_received_tail_is_not_consumed_again_by_second_delegation(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 100, '前に'), transcript(100, 300, '進んで'),
                          delegation(150, 'first'))
        self.utterance.reset_mock()
        await socket.feed(delegation(150, 'different-id'), delegation(300, 'tail-end'))
        self.utterance.assert_not_awaited()
        self.assertEqual(self.adapter.last_offset, 300)
        self.assertEqual(self.adapter.diagnostics()['delegationWithoutTranscript'], 2)

    async def test_next_fragment_starting_at_consumed_end_is_accepted(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 300, '前に進んで'), delegation(100, 'first'))
        self.utterance.reset_mock()
        await socket.feed(transcript(300, 500, '止まって'), delegation(300, 'next'))
        self.utterance.assert_awaited_once_with('止まって', 'next', self.adapter.context_generation)
        self.assertEqual(self.adapter.last_offset, 500)

    async def test_fragment_start_after_offset_waits_for_later_delegation(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 200, '前に進んで'), transcript(400, 600, '止まって'),
                          delegation(100, 'first'))
        self.utterance.assert_awaited_once_with('前に進んで', 'first', self.adapter.context_generation)
        self.assertEqual(self.adapter.last_offset, 200)
        self.assertEqual(self.adapter.max_offset, 600)
        self.utterance.reset_mock()
        await socket.feed(delegation(400, 'next'))
        self.utterance.assert_awaited_once_with('止まって', 'next', self.adapter.context_generation)
        self.assertEqual(self.adapter.last_offset, 600)

    async def test_cursor_advances_to_offset_when_offset_exceeds_selected_end(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 200, '前に進んで'), delegation(300, 'first'))
        self.assertEqual(self.adapter.last_offset, 300)
        self.utterance.reset_mock()
        await socket.feed(transcript(250, 290, '遅れた断片'), delegation(300, 'old-tail'),
                          transcript(300, 500, '止まって'), delegation(350, 'next'))
        self.utterance.assert_awaited_once_with('止まって', 'next', self.adapter.context_generation)

    async def test_context_clear_preserves_consumed_tail_and_allows_adjacent_new_audio(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 500, '前に進んで'), delegation(200, 'first'))
        self.adapter.clear_context()
        self.assertEqual(self.adapter.last_offset, 500)
        self.assertFalse(self.adapter.fragments)
        self.utterance.reset_mock()
        await socket.feed(transcript(0, 500, '古い指示'), delegation(200, 'late'),
                          transcript(500, 700, '止まって'), delegation(500, 'next'))
        self.utterance.assert_awaited_once_with('止まって', 'next', self.adapter.context_generation)

    async def test_reconnect_resets_consumed_tail_cursor(self):
        old = await self.connect()
        await old.feed(transcript(1000, 1500, '古い指示'), delegation(1100, 'same-id'))
        self.assertEqual(self.adapter.last_offset, 1500)
        await self.adapter.stop(graceful=False)
        new = await self.connect()
        self.utterance.reset_mock()
        await new.feed(transcript(0, 200, '新しい指示'), delegation(0, 'same-id'))
        self.utterance.assert_awaited_once_with('新しい指示', 'same-id', self.adapter.context_generation)

    async def test_zero_length_received_fragment_is_not_consumed_twice(self):
        socket = await self.connect()
        await socket.feed(transcript(100, 100, '止まって'), delegation(100, 'first'),
                          delegation(100, 'different-id'))
        self.utterance.assert_awaited_once_with('止まって', 'first', self.adapter.context_generation)

    async def test_context_clear_never_moves_consumption_cursor_backwards(self):
        socket = await self.connect()
        await socket.feed(transcript(0, 200, '前に進んで'), delegation(300, 'first'))
        self.adapter.clear_context()
        self.assertEqual(self.adapter.last_offset, 300)
        self.utterance.reset_mock()
        await socket.feed(transcript(250, 290, '古い末尾'), delegation(300, 'late'),
                          transcript(300, 500, '止まって'), delegation(350, 'next'))
        self.utterance.assert_awaited_once_with('止まって', 'next', self.adapter.context_generation)


if __name__ == '__main__':
    unittest.main()
