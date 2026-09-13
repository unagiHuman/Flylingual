"""Network-free contract tests for synthetic-voice diagnostics."""
import asyncio
import base64
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import aiohttp

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.conversation import ConversationAdapter, ConversationError
from Runtime.Bridge.server import Bridge


class FakeLoop:
    def __init__(self): self.now = 0.0
    def time(self): return self.now


class EventSocket:
    def __init__(self, events): self.events = iter(events)

    def __aiter__(self): return self

    async def __anext__(self):
        try: event = next(self.events)
        except StopIteration: raise StopAsyncIteration
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(event))


class VoiceTestDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def make_bridge(self):
        bridge = Bridge(copy.deepcopy(_DEFAULT))
        bridge.control_ws = object()
        bridge.control_queue = asyncio.Queue(maxsize=32)
        bridge.conversation.input_audio = AsyncMock()
        bridge.conversation_accepting = True
        bridge.conversation_interaction = 'control'
        bridge.conversation_generation = 9
        return bridge

    async def test_optin_allowlist_excludes_pcm_and_text_from_control_diagnostic(self):
        bridge = self.make_bridge()
        await bridge.command({'type': 'voice_test_observation', 'enabled': True})
        enabled = bridge.control_queue.get_nowait()
        self.assertEqual(enabled, {'type': 'voice_test_observation', 'enabled': True})
        self.assertTrue(bridge.voice_test_observation)
        self.assertTrue(bridge.conversation.voice_test_observation)

        bridge.log('command_submitted', requestId=4, fixtureId='forward_01',
                   audio='base64-pcm-must-not-leak', text='transcript-must-not-leak', unknown='discarded')
        diagnostic = bridge.control_queue.get_nowait()
        self.assertEqual(diagnostic['type'], 'voice_test_diagnostic')
        self.assertEqual(diagnostic['event'], 'command_submitted')
        self.assertEqual(diagnostic['fixtureId'], 'forward_01')
        self.assertNotIn('audio', diagnostic)
        self.assertNotIn('text', diagnostic)
        self.assertNotIn('unknown', diagnostic)

    async def test_tag_requires_optin_and_current_epoch_generation(self):
        bridge = self.make_bridge()
        encoded = base64.b64encode(bytes(4800)).decode('ascii')
        event = {'type': 'audio', 'audio': encoded, 'controlEpoch': bridge.arbiter.epoch,
                 'conversationGeneration': bridge.conversation_generation,
                 'fixtureId': 'forward_01', 'fixtureChunkIndex': 3}
        with self.assertRaisesRegex(ControlError, 'invalid_voice_fixture_tag'):
            await bridge.command(event)

        await bridge.command({'type': 'voice_test_observation', 'enabled': True})
        bridge.control_queue.get_nowait()
        with self.assertRaisesRegex(ControlError, 'old_audio_epoch'):
            await bridge.command({**event, 'controlEpoch': bridge.arbiter.epoch - 1})
        with self.assertRaisesRegex(ControlError, 'old_conversation_generation'):
            await bridge.command({**event, 'conversationGeneration': bridge.conversation_generation - 1})
        for missing in ('fixtureId', 'fixtureChunkIndex'):
            with self.assertRaisesRegex(ControlError, 'invalid_voice_fixture_tag'):
                await bridge.command({k: v for k, v in event.items() if k != missing})
        await bridge.command(event)
        bridge.conversation.input_audio.assert_awaited_once_with(
            encoded, {'fixtureId': 'forward_01', 'fixtureChunkIndex': 3})

    async def test_queue_tag_becomes_post_send_diagnostic_not_live_payload(self):
        events = AsyncMock()
        adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), events, AsyncMock())
        adapter.state = 'live'
        adapter.voice_test_observation = True
        await adapter.input_audio(base64.b64encode(bytes(4800)).decode('ascii'),
                                  {'fixtureId': 'stop_02', 'fixtureChunkIndex': 7})
        clock, sent = FakeLoop(), []

        async def sleep(delay): clock.now += delay

        async def send(event):
            sent.append(event)
            if len(sent) == 2: raise ConversationError('test_stop')

        adapter._send_event = send
        from unittest.mock import patch
        with patch('Runtime.Bridge.conversation.asyncio.get_running_loop', return_value=clock), \
             patch('Runtime.Bridge.conversation.asyncio.sleep', side_effect=sleep):
            await adapter._send_audio()

        self.assertEqual(set(sent[0]), {'type', 'audio'})
        self.assertEqual(sent[0]['type'], 'session.input_audio.append')
        self.assertNotIn('fixtureId', sent[0])
        self.assertNotIn('fixtureChunkIndex', sent[0])
        diagnostic = events.await_args.args[0]
        self.assertEqual(diagnostic, {'type': 'voice_test_diagnostic', 'event': 'audio_fixture_sent',
                                      'fixtureId': 'stop_02', 'fixtureChunkIndex': 7,
                                      'audioStartMs': 0.0, 'audioEndMs': 100.0})

    async def test_clear_context_drops_tagged_queue_before_send(self):
        adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), AsyncMock(), AsyncMock())
        adapter.state = 'live'
        await adapter.input_audio(base64.b64encode(bytes(4800)).decode('ascii'),
                                  {'fixtureId': 'old_01', 'fixtureChunkIndex': 0})
        generation = adapter.context_generation
        adapter.clear_context()
        self.assertEqual(adapter.context_generation, generation + 1)
        self.assertTrue(adapter.audio_queue.empty())

    async def test_inflight_generation_change_does_not_relabel_old_fixture(self):
        events = AsyncMock()
        adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), events, AsyncMock())
        adapter.state = 'live'
        adapter.voice_test_observation = True
        await adapter.input_audio(base64.b64encode(bytes(4800)).decode('ascii'),
                                  {'fixtureId': 'old_01', 'fixtureChunkIndex': 0})
        clock = FakeLoop()
        calls = 0

        async def sleep(delay): clock.now += delay

        async def send(event):
            nonlocal calls
            calls += 1
            if calls == 1: adapter.clear_context()
            else: raise ConversationError('test_stop')

        adapter._send_event = send
        from unittest.mock import patch
        with patch('Runtime.Bridge.conversation.asyncio.get_running_loop', return_value=clock), \
             patch('Runtime.Bridge.conversation.asyncio.sleep', side_effect=sleep):
            await adapter._send_audio()
        events.assert_not_awaited()
        self.assertEqual(adapter.sent_audio_samples, 2400)

    async def test_delegation_diagnostic_exposes_offsets_without_transcript(self):
        events, utterance = AsyncMock(), AsyncMock()
        adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), events, utterance)
        adapter.voice_test_observation = True
        adapter.ws = EventSocket([
            {'type': 'session.input_transcript.delta', 'start_ms': 120, 'end_ms': 240, 'delta': 'private words'},
            {'type': 'session.delegation.created', 'offset_ms': 240,
             'delegation': {'id': 'delegation-01', 'target': 'client'}},
        ])
        await adapter._read()
        diagnostic = next(call.args[0] for call in events.await_args_list
                          if call.args[0].get('type') == 'voice_test_diagnostic')
        self.assertEqual(diagnostic, {'type': 'voice_test_diagnostic', 'event': 'delegation_observed',
                                      'delegationId': 'delegation-01', 'startMs': 120,
                                      'endMs': 240, 'offsetMs': 240})
        self.assertNotIn('text', diagnostic)
        self.assertNotIn('private words', json.dumps(diagnostic))


if __name__ == '__main__':
    unittest.main()
