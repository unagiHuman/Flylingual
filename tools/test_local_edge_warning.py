"""Bridge notification unit tests; no Brain or audio execution."""
import copy
import unittest
from unittest.mock import AsyncMock
from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.server import Bridge
from Runtime.Bridge.control import ControlError

class EdgeWarningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.b = Bridge(copy.deepcopy(_DEFAULT))
        self.b.control_ws = object()
        self.b.conversation_accepting = True
        self.b.conversation.state = 'live'
        self.b.arbiter.owner = 'gpt'
        self.b.arbiter.resume()
        self.b.conversation.append = AsyncMock()
        self.b.inhibit = AsyncMock()
        self.sequence = 0

    def event(self, **changes):
        self.sequence += 1
        value = dict(type='local_observation', controlEpoch=self.b.arbiter.epoch,
                     conversationGeneration=self.b.conversation_generation,
                     sequence=self.sequence, ageMs=0, groundPresent=True,
                     leftEdge='near', rightEdge='safe', forwardBlocked=False, bodyUnsafe=False)
        value.update(changes)
        return value

    async def test_danger_once_safe_rearms_unknown_does_not(self):
        for changes in ({}, {}, {'leftEdge':'unknown'}, {}):
            await self.b.accept_local_observation(self.event(**changes))
        self.assertEqual(self.b.conversation.append.await_count, 1)
        await self.b.accept_local_observation(self.event(leftEdge='safe'))
        await self.b.accept_local_observation(self.event(leftEdge='safe', groundPresent=False))
        self.assertEqual(self.b.conversation.append.await_count, 2)
        self.assertIn('もうすぐ落ちそうです。', self.b.conversation.append.await_args.args[1])
        self.b.inhibit.assert_not_awaited()

    async def test_reject_old_generation_and_chat_only(self):
        with self.assertRaises(ControlError):
            await self.b.accept_local_observation(self.event(conversationGeneration=-1))
        self.b.conversation_interaction = 'chat_only'
        with self.assertRaises(ControlError):
            await self.b.accept_local_observation(self.event())
        self.b.conversation.append.assert_not_awaited()

    async def test_stale_and_inactive_do_not_speak(self):
        await self.b.accept_local_observation(self.event(ageMs=750))
        self.b.conversation_accepting = False
        await self.b.accept_local_observation(self.event())
        self.b.conversation.append.assert_not_awaited()

    async def test_new_generation_rearms(self):
        await self.b.accept_local_observation(self.event())
        self.b.conversation_generation += 1
        await self.b.accept_local_observation(self.event())
        self.assertEqual(self.b.conversation.append.await_count, 2)

if __name__ == '__main__':
    unittest.main()
