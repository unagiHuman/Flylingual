"""Pure state/contract checks, not Brain or microphone acceptance trials."""
import asyncio
import base64
import copy
import unittest
from unittest.mock import AsyncMock

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.server import Bridge


class NativeConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge(copy.deepcopy(_DEFAULT))
        self.bridge.control_queue = asyncio.Queue(maxsize=128)
        self.bridge.control_ws = object()
        # Network-free collaborators; no invented Brain frames or motor output.
        self.bridge.conversation.start = AsyncMock()
        self.bridge.conversation.stop = AsyncMock()
        self.bridge.conversation.input_audio = AsyncMock()

    async def asyncTearDown(self):
        for task in tuple(self.bridge.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.bridge.tasks), return_exceptions=True)

    async def start_chat(self):
        await self.bridge.command({'type': 'conversation_start', 'interaction': 'chat_only',
                                   'controlEpoch': self.bridge.arbiter.epoch})
        await self.bridge.conversation_operation

    async def test_chat_inhibits_without_brain_and_accepts_audio_by_generation(self):
        await self.start_chat()
        self.assertTrue(self.bridge.arbiter.inhibited)
        self.assertEqual(self.bridge.arbiter.owner, 'observer')
        self.assertFalse(self.bridge.resume_ready())
        generation = self.bridge.conversation_generation
        await self.bridge.inhibit('stale_brain', send_stop=False)
        self.assertEqual(generation, self.bridge.conversation_generation)
        await self.bridge.command({'type': 'audio', 'conversationGeneration': generation,
                                   'audio': base64.b64encode(bytes(4800)).decode()})
        self.bridge.conversation.input_audio.assert_awaited_once()

    async def test_chat_rejects_every_control_entry(self):
        await self.start_chat()
        for event in ({'type': 'resume'}, {'type': 'set_owner', 'owner': 'gpt'},
                      {'type': 'set_action', 'action': 'FORWARD'},
                      {'type': 'player_text', 'text': 'forward'}):
            with self.assertRaisesRegex(ControlError, 'chat_only_cannot_control'):
                await self.bridge.command(event)
        with self.assertRaisesRegex(ControlError, 'chat_only_cannot_control'):
            await self.bridge.submit('FORWARD', 'gpt', 'id')

    async def test_old_and_boolean_generations_rejected(self):
        await self.start_chat()
        for generation in (-1, True, None):
            with self.assertRaisesRegex(ControlError, 'old_conversation_generation'):
                await self.bridge.command({'type': 'audio', 'conversationGeneration': generation, 'audio': 'AAA='})
        self.bridge.conversation.input_audio.assert_not_awaited()

    async def test_stop_discards_late_output_and_stops_input(self):
        await self.start_chat()
        generation = self.bridge.conversation_generation
        await self.bridge.command({'type': 'conversation_stop'})
        await self.bridge.conversation_operation
        count = self.bridge.control_queue.qsize()
        await self.bridge.conversation_event({'type': 'audio', 'audio': 'AAA='})
        await self.bridge.conversation_event({'type': 'conversation_text', 'role': 'assistant', 'text': 'late'})
        self.assertEqual(count, self.bridge.control_queue.qsize())
        self.assertGreater(self.bridge.conversation_generation, generation)
        with self.assertRaisesRegex(ControlError, 'old_conversation_generation'):
            await self.bridge.command({'type': 'audio', 'conversationGeneration': generation, 'audio': 'AAA='})

    async def test_pending_start_cancelled_before_stop_and_explicit_restart(self):
        entered = asyncio.Event()
        async def pending():
            entered.set()
            await asyncio.Event().wait()
        self.bridge.conversation.start = pending
        await self.bridge.command({'type': 'conversation_start', 'interaction': 'chat_only',
                                   'controlEpoch': self.bridge.arbiter.epoch})
        await entered.wait()
        await self.bridge.command({'type': 'conversation_stop'})
        with self.assertRaisesRegex(ControlError, 'already_started_or_stopping'):
            await self.bridge.command({'type': 'conversation_start'})
        await self.bridge.conversation_operation
        self.bridge.conversation.stop.assert_awaited_once()
        self.assertFalse(self.bridge.conversation_accepting)

    async def test_delegation_cannot_reach_intent_translator(self):
        await self.start_chat()
        self.bridge.conversation.interpret = AsyncMock()
        self.bridge.conversation.append = AsyncMock()
        await self.bridge.voice_utterance('forward', 'd1', self.bridge.conversation.context_generation)
        self.bridge.conversation.interpret.assert_not_awaited()
        self.bridge.conversation.append.assert_awaited_once()
        self.assertEqual(len(self.bridge.intent_tasks), 0)

    async def test_legacy_audio_still_requires_epoch(self):
        with self.assertRaisesRegex(ControlError, 'old_audio_epoch'):
            await self.bridge.command({'type': 'audio', 'conversationGeneration': 0, 'audio': 'AAA='})
        await self.bridge.command({'type': 'audio', 'controlEpoch': self.bridge.arbiter.epoch, 'audio': 'AAA='})
        self.bridge.conversation.input_audio.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
