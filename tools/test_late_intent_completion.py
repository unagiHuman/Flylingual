"""No-network admission tests for delayed classification/reinterpretation results."""
import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationError
from Runtime.Bridge.server import Bridge
from tools.test_persistent_execution import action


class LateIntentCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.b = Bridge(copy.deepcopy(_DEFAULT))
        self.b.log = Mock(); self.b.emit = Mock()
        self.b.conversation.state = 'live'
        self.b.conversation.append = AsyncMock()
        self.b.conversation_accepting = True
        self.b.arbiter.owner = 'gpt'; self.b.arbiter.resume()
        self.b.voice_control_epoch = self.b.arbiter.epoch
        self.b.adapter = SimpleNamespace(connected=True, send_action=AsyncMock())
        self.b.summary = Mock(return_value={'stale': False, 'interpretation': 'unknown'})
        self.b.inhibit = AsyncMock()

    async def delayed(self, fail=False, swallow_cancel=False):
        entered, release = asyncio.Event(), asyncio.Event()
        async def interpret(*_):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                if not swallow_cancel:
                    raise
                await release.wait()
            if fail:
                raise ConversationError('intent_translation_failed')
            return action('FORWARD', duration=1000)
        self.b.conversation.interpret = AsyncMock(side_effect=interpret)
        task = asyncio.create_task(self.b.player_intent('前へ', 'old-input', self.b.arbiter.epoch,
                                                       self.b.intent_revision, None))
        await entered.wait()
        return task, release

    async def test_changed_conversation_generation_drops_late_success(self):
        task, release = await self.delayed()
        self.b.conversation_generation += 1
        release.set(); await task
        self.b.adapter.send_action.assert_not_awaited()
        self.b.conversation.append.assert_not_awaited()
        self.b.inhibit.assert_not_awaited()

    async def test_changed_context_generation_drops_late_success(self):
        task, release = await self.delayed()
        self.b.conversation.context_generation += 1
        release.set(); await task
        self.b.adapter.send_action.assert_not_awaited()
        self.b.inhibit.assert_not_awaited()

    async def test_new_stop_revision_drops_old_success(self):
        task, release = await self.delayed()
        self.b.intent_revision += 1
        release.set(); await task
        self.b.adapter.send_action.assert_not_awaited()
        self.b.inhibit.assert_not_awaited()

    async def test_cancel_suppressing_provider_error_cannot_stop_new_execution(self):
        task, release = await self.delayed(fail=True, swallow_cancel=True)
        self.b.intent_revision += 1
        self.b.activate_execution('new-input', 'TURN_L', 'until_next_command', None)
        current = self.b.active_execution
        task.cancel(); await asyncio.sleep(0)
        release.set(); await task
        self.assertIs(self.b.active_execution, current)
        self.b.inhibit.assert_not_awaited()
        self.b.conversation.append.assert_not_awaited()
        self.b.adapter.send_action.assert_not_awaited()

    async def test_old_session_error_cannot_inhibit_new_session(self):
        task, release = await self.delayed(fail=True)
        self.b.conversation_generation += 1
        release.set(); await task
        self.b.inhibit.assert_not_awaited()
        self.b.conversation.append.assert_not_awaited()

    async def test_expired_delayed_result_is_not_submitted(self):
        now = [100.0]
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: now[0])):
            task, release = await self.delayed()
            now[0] += self.b.config['control']['maxIntentAgeMs'] / 1000 + .001
            release.set(); await task
        self.b.adapter.send_action.assert_not_awaited()
        self.assertTrue(any(call.args[0].get('reason') == 'expired_intent'
                            for call in self.b.emit.call_args_list if call.args))

    async def test_current_provider_failure_still_inhibits(self):
        task, release = await self.delayed(fail=True)
        release.set(); await task
        self.b.inhibit.assert_awaited_once_with('intent_service_failed')


if __name__ == '__main__':
    unittest.main()
