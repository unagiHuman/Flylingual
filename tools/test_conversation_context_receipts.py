"""Context receipt contracts only; no API or live process."""
import asyncio
import copy
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from Runtime.Bridge.conversation import ConversationAdapter, ConversationError
from Runtime.Bridge.config import _DEFAULT


class ContextReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = AsyncMock()
        self.adapter = a = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), self.events, AsyncMock())
        a.mode = 'live'
        a.state = 'live'
        a.ws = SimpleNamespace(closed=False, close=AsyncMock())
        a._send_event = AsyncMock()
        self.trace = dict(brainSequence=23, brainSessionId='session-1', brainInstanceId='instance-1',
                          controlEpoch=2, conversationGeneration=3, language='ja', sourceId='idle_swatter', requestId=-4, active=True)

    def receipts(self):
        return [c.args[0] for c in self.events.await_args_list if c.args[0]['type'] == 'conversation_context_receipt']

    async def test_sent_then_exact_channel_and_id_acceptance_no_content(self):
        a = self.adapter
        content = 'Measured rate: right 40 Hz, left 20 Hz.'
        rid = await a.append('thinking', content, trace=self.trace)
        self.assertEqual(a._send_event.await_args.args[0]['event_id'], rid)
        self.assertNotIn('trace', a._send_event.await_args.args[0])
        self.assertEqual(self.receipts()[0]['contentHash'], hashlib.sha256(content.encode()).hexdigest())
        await a._context_appended(dict(type='session.thinking.appended', event_id=rid))
        self.assertEqual([e['stage'] for e in self.receipts()], ['sent', 'accepted'])
        self.assertTrue(all(e['current'] for e in self.receipts()))
        self.assertNotIn(content, repr(self.receipts()))
        self.assertEqual(a.context_receipts, {})

    async def test_client_event_id_is_authoritative_and_recorded(self):
        a = self.adapter
        rid = await a.append('commentary', 'text', trace=self.trace)
        await a._context_appended(dict(type='session.commentary.appended',
                                      event_id='server-event-1', client_event_id=rid))
        self.assertEqual(self.receipts()[-1]['stage'], 'accepted')
        self.assertEqual(self.receipts()[-1]['eventId'], rid)
        self.assertEqual(self.receipts()[-1]['correlationField'], 'client_event_id')

    async def test_wrong_or_null_client_id_never_falls_back_to_matching_event_id(self):
        a = self.adapter
        rid = await a.append('thinking', 'text', trace=self.trace)
        for wrong in ('unknown', None, 1, ''):
            await a._context_appended(dict(type='session.thinking.appended', event_id=rid, client_event_id=wrong))
            self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')
            self.assertIn(rid, a.context_receipts)
        await a._context_appended(dict(type='session.thinking.appended', event_id=rid))
        self.assertEqual(self.receipts()[-1]['stage'], 'accepted')
        self.assertEqual(self.receipts()[-1]['correlationField'], 'event_id')

    async def test_no_id_wrong_id_wrong_channel_duplicates_are_unmatched(self):
        a = self.adapter
        rid = await a.append('commentary', 'text', trace=self.trace)
        for event in [dict(type='session.commentary.appended'),
                      dict(type='session.commentary.appended', event_id='unknown-secret'),
                      dict(type='session.thinking.appended', event_id=rid)]:
            await a._context_appended(event)
            self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')
            self.assertFalse(self.receipts()[-1]['current'])
        await a._context_appended(dict(type='session.commentary.appended', event_id=rid))
        await a._context_appended(dict(type='session.commentary.appended', event_id=rid))
        self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')
        self.assertNotIn('unknown-secret', repr(self.receipts()))

    async def test_clear_and_stop_discard_pending_and_late_ack(self):
        a = self.adapter
        for stop in (False, True):
            a.closing = False
            a.ws = SimpleNamespace(closed=False, close=AsyncMock())
            rid = await a.append('thinking', 'text', trace=self.trace)
            if stop: await a.stop(graceful=False)
            else: a.clear_context()
            await a._context_appended(dict(type='session.thinking.appended', event_id=rid))
            self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')
            self.assertEqual(a.context_receipts, {})

    async def test_bounded_and_oldest_ack_not_promoted(self):
        a = self.adapter
        first = await a.append('thinking', 'text', trace=self.trace)
        for _ in range(128):
            await a.append('thinking', 'text', trace=self.trace)
        self.assertEqual(len(a.context_receipts), 128)
        await a._context_appended(dict(type='session.thinking.appended', event_id=first))
        self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')

    async def test_invalid_trace_is_not_sent_or_logged(self):
        for change in ({'content': 'secret'}, {'brainSequence': True}, {'language': 'secret'},
                       {'sourceId': 'secret'}, {'brainSessionId': 'Bearer secret'}):
            with self.assertRaises(ConversationError):
                await self.adapter.append('thinking', 'text', trace={**self.trace, **change})
        self.adapter._send_event.assert_not_awaited()
        self.events.assert_not_awaited()

    async def test_send_failure_and_no_live_emit_no_sent_receipt(self):
        a = self.adapter
        a._send_event.side_effect = ConversationError('live_send_failed')
        with self.assertRaises(ConversationError):
            await a.append('thinking', 'text', trace=self.trace)
        self.assertEqual(a.context_receipts, {})
        self.assertEqual(self.receipts(), [])
        a.mode = 'text'
        self.assertIsNone(await a.append('thinking', 'text', trace=self.trace))

    async def test_ack_during_send_is_reported_after_sent(self):
        a = self.adapter
        async def send(event):
            await a._context_appended(dict(type='session.thinking.appended', event_id=event['event_id']))
        a._send_event.side_effect = send
        await a.append('thinking', 'text', trace=self.trace)
        self.assertEqual([e['stage'] for e in self.receipts()], ['sent', 'accepted'])

    async def test_clear_during_send_cannot_receive_current_success(self):
        a = self.adapter
        async def send(event): a.clear_context()
        a._send_event.side_effect = send
        rid = await a.append('thinking', 'text', trace=self.trace)
        self.assertFalse(self.receipts()[-1]['current'])
        await a._context_appended(dict(type='session.thinking.appended', event_id=rid))
        self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')

    async def test_expired_receipt_cannot_become_current(self):
        a = self.adapter
        rid = await a.append('thinking', 'text', trace=self.trace)
        a.context_receipts[rid]['createdAt'] -= 31
        await a._context_appended(dict(type='session.thinking.appended', event_id=rid))
        self.assertEqual(self.receipts()[-1]['stage'], 'unmatched')
        self.assertFalse(self.receipts()[-1]['current'])

    async def test_untraced_legacy_return_id_without_new_sent_event(self):
        rid = await self.adapter.append('thinking', 'text', 'delegation')
        self.assertIsInstance(rid, str)
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.adapter._send_event.await_args.args[0]['delegation_id'], 'delegation')


if __name__ == '__main__':
    unittest.main()
