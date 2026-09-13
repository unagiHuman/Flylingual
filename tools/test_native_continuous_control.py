"""Protocol-only TTL tests; no API, Brain frames, motor simulation or Unity."""
import asyncio
import copy
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.brain_adapter import BrainAdapterError
from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.server import Bridge


class NativeContinuousControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge(copy.deepcopy(_DEFAULT))
        b = self.bridge
        b.adapter = SimpleNamespace(connected=True, status={}, send_action=AsyncMock())
        b.motor_writer = Mock()
        b.summary = Mock(return_value={'stale': False})
        b.log = Mock()
        b.conversation.state = 'live'
        b.conversation.append = AsyncMock()
        b.conversation.start = AsyncMock()
        b.conversation.stop = AsyncMock()
        b.conversation.clear_context = Mock(wraps=b.conversation.clear_context)
        b.conversation_accepting = True
        b.native_voice_control = True
        b.arbiter.owner = 'gpt'
        b.arbiter.resume()
        b.voice_control_epoch = b.arbiter.epoch
        b.arbiter.accept('gpt', 'FORWARD', 'original-command', b.arbiter.epoch, 1000)
        b.arbiter.deadline = time.monotonic() - 1

    async def asyncTearDown(self):
        tasks = tuple(self.bridge.tasks | self.bridge.intent_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_expiry_sends_stop_once_without_revoking_control_or_pending_intent(self):
        b = self.bridge
        pending = b.task(asyncio.Event().wait(), intent=True)
        previous = (b.arbiter.epoch, b.voice_control_epoch, b.conversation_generation,
                    b.conversation.context_generation, b.intent_revision)
        await b.check_control_safety()
        await b.check_control_safety()
        b.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertEqual(b.requests[1]['source'], 'safety')
        self.assertTrue(b.requests[1]['commandId'].startswith('expired-stop-'))
        self.assertIsNone(b.arbiter.deadline)
        self.assertFalse(b.arbiter.inhibited)
        self.assertEqual(previous, (b.arbiter.epoch, b.voice_control_epoch, b.conversation_generation,
                                  b.conversation.context_generation, b.intent_revision))
        self.assertFalse(pending.done())
        b.motor_writer.close.assert_not_called()
        b.conversation.clear_context.assert_not_called()
        b.log.assert_any_call('command_expired', continuedListening=True)
        with self.assertRaisesRegex(ControlError, 'duplicate_command'):
            b.arbiter.accept('gpt', 'FORWARD', 'original-command', b.arbiter.epoch, 1000)

    async def test_fresh_voice_intent_after_expiry_is_accepted_without_resume(self):
        b = self.bridge
        await b.check_control_safety()
        b.conversation.interpret = AsyncMock(return_value={
            'kind': 'action', 'action': 'TURN_L', 'validForMs': 4000, 'reply': ''})
        await b.player_intent('turn left', 'new-voice-command', b.arbiter.epoch,
                              b.intent_revision, 'new-delegation')
        self.assertEqual([call.args[0] for call in b.adapter.send_action.await_args_list], ['STOP', 'TURN_L'])
        self.assertEqual(b.requests[2]['commandId'], 'new-voice-command')
        self.assertFalse(b.arbiter.inhibited)
        self.assertGreater(b.arbiter.deadline, time.monotonic())
        self.assertLessEqual(b.arbiter.deadline, time.monotonic() + 4)

    async def test_new_deadline_received_during_stop_delivery_is_not_erased(self):
        b = self.bridge
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(action, request_id):
            if action == 'STOP':
                entered.set()
                await release.wait()

        b.adapter.send_action.side_effect = send
        check = b.task(b.check_control_safety())
        await asyncio.wait_for(entered.wait(), timeout=1)
        self.assertIsNone(b.arbiter.deadline)
        b.arbiter.accept('gpt', 'TURN_R', 'new-command', b.arbiter.epoch, 4000)
        new_deadline = b.arbiter.deadline
        await b.submit('TURN_R', 'gpt', 'new-command')
        release.set()
        await check
        self.assertEqual(b.arbiter.deadline, new_deadline)
        self.assertEqual([call.args[0] for call in b.adapter.send_action.await_args_list], ['STOP', 'TURN_R'])

    async def test_stale_brain_precedes_expiry_and_keeps_full_inhibition(self):
        b = self.bridge
        b.summary.return_value = {'stale': True}
        epoch = b.arbiter.epoch
        await b.check_control_safety()
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.reason, 'stale_brain')
        self.assertGreater(b.arbiter.epoch, epoch)
        self.assertIsNone(b.voice_control_epoch)
        b.motor_writer.close.assert_called_once()
        b.conversation.clear_context.assert_called_once()
        self.assertFalse(any(call.args[0] == 'command_expired' for call in b.log.call_args_list))

    async def test_legacy_control_expiry_retains_full_inhibition(self):
        b = self.bridge
        b.native_voice_control = False
        await b.check_control_safety()
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.reason, 'command_expired')
        b.motor_writer.close.assert_called_once()
        b.conversation.clear_context.assert_called_once()
        b.log.assert_any_call('command_expired', continuedListening=False)

    async def test_obsolete_voice_epoch_does_not_keep_control(self):
        b = self.bridge
        b.voice_control_epoch -= 1
        await b.check_control_safety()
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.reason, 'command_expired')

    async def test_stop_delivery_error_falls_back_to_full_inhibition(self):
        b = self.bridge
        b.adapter.send_action.side_effect = [BrainAdapterError('write_failed'), None]
        await b.check_control_safety()
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.reason, 'expired_stop_send_failed')
        self.assertIsNone(b.voice_control_epoch)
        b.motor_writer.close.assert_called_once()
        b.conversation.clear_context.assert_called_once()
        self.assertEqual([call.args[0] for call in b.adapter.send_action.await_args_list], ['STOP', 'STOP'])

    async def test_explicit_emergency_stop_still_revokes_control(self):
        b = self.bridge
        await b.check_control_safety()
        epoch = b.arbiter.epoch
        await b.command({'type': 'emergency_stop'})
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.reason, 'emergency_stop')
        self.assertGreater(b.arbiter.epoch, epoch)
        self.assertIsNone(b.voice_control_epoch)
        b.motor_writer.close.assert_called_once()

    async def test_opt_in_cleared_on_stop_and_chat_only_start(self):
        b = self.bridge
        b.stop_conversation_session()
        await b.conversation_operation
        self.assertFalse(b.native_voice_control)
        b.conversation.state = 'off'
        await b.command({'type': 'conversation_start', 'interaction': 'control',
                         'nativeVoiceControl': True, 'controlEpoch': b.arbiter.epoch})
        await b.conversation_operation
        self.assertTrue(b.native_voice_control)
        b.conversation.state = 'off'
        await b.command({'type': 'conversation_start', 'interaction': 'chat_only',
                         'controlEpoch': b.arbiter.epoch})
        await b.conversation_operation
        self.assertFalse(b.native_voice_control)
        self.assertTrue(b.arbiter.inhibited)
        self.assertEqual(b.arbiter.owner, 'observer')

    async def interpret_after(self, action, proposed_ms, elapsed_seconds, *,
                              cancel_wait_seconds=0, change_epoch=False,
                              change_revision=False):
        b = self.bridge
        clock = SimpleNamespace(now=100.0)
        clock.monotonic = lambda: clock.now

        async def interpret(*_):
            clock.now += elapsed_seconds
            return {'kind': 'action', 'action': action, 'plan': None,
                    'validForMs': proposed_ms, 'reply': ''}

        async def cancel_previous():
            clock.now += cancel_wait_seconds
            if change_epoch:
                b.arbiter.epoch += 1
            if change_revision:
                b.intent_revision += 1

        b.conversation.interpret = AsyncMock(side_effect=interpret)
        b.plans.cancel_and_wait = AsyncMock(side_effect=cancel_previous)
        # Replace module bindings, never the global time module used by asyncio.
        # The same clock makes the actual arbiter deadline measurable exactly.
        with patch('Runtime.Bridge.server.time', clock), patch('Runtime.Bridge.control.time', clock):
            await b.player_intent('protocol request', 'fresh-voice', b.arbiter.epoch,
                                  b.intent_revision, 'delegation')
        return clock.now

    async def test_stop_zero_proposed_duration_uses_freshness_and_submits(self):
        await self.interpret_after('STOP', 0, .25)
        self.bridge.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertIsNone(self.bridge.arbiter.deadline)
        self.bridge.log.assert_any_call('intent_classified', commandId='fresh-voice',
            source='voice', kind='action', action='STOP', plan=None, proposalValidForMs=0, interpretationMs=250,
            interpretRoute=None)

    async def test_stop_after_four_second_interpretation_remains_fresh(self):
        await self.interpret_after('STOP', 4000, 4.5)
        self.bridge.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertIsNone(self.bridge.arbiter.deadline)
        self.assertFalse(self.bridge.arbiter.inhibited)

    async def test_stop_older_than_eight_seconds_is_rejected(self):
        await self.interpret_after('STOP', 0, 8.5)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_stop_exactly_at_freshness_deadline_is_rejected(self):
        await self.interpret_after('STOP', 0, 8)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_movement_zero_duration_still_rejected(self):
        await self.interpret_after('FORWARD', 0, .25)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='invalid_command_duration')

    async def test_real_failure_4766ms_interpretation_gets_full_four_second_movement(self):
        accepted_at = await self.interpret_after('FORWARD', 4000, 4.766)
        self.bridge.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.bridge.arbiter.deadline, accepted_at + 4)
        self.assertFalse(self.bridge.arbiter.inhibited)
        self.assertEqual(self.bridge.requests[1]['source'], 'gpt')

    async def test_movement_just_before_freshness_limit_gets_full_duration(self):
        accepted_at = await self.interpret_after('FORWARD', 4000, 7.999)
        self.bridge.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.bridge.arbiter.deadline, accepted_at + 4)

    async def test_movement_at_freshness_limit_is_not_submitted(self):
        await self.interpret_after('FORWARD', 4000, 8)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_movement_after_freshness_limit_is_not_submitted(self):
        await self.interpret_after('FORWARD', 4000, 8.001)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_movement_over_maximum_duration_is_still_rejected(self):
        await self.interpret_after('FORWARD', 8001, .25)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='invalid_command_duration')

    async def test_freshness_limit_is_independent_of_shorter_action_limit(self):
        self.bridge.config['control']['maxActionMs'] = 2000
        self.bridge.arbiter.max_ms = 2000
        accepted_at = await self.interpret_after('FORWARD', 1000, 4.766)
        self.bridge.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.bridge.arbiter.deadline, accepted_at + 1)

    async def test_configured_intent_age_limit_is_used(self):
        self.bridge.config['control']['maxIntentAgeMs'] = 3000
        await self.interpret_after('FORWARD', 4000, 3)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_cancel_wait_that_reaches_freshness_limit_rejects_movement(self):
        await self.interpret_after('FORWARD', 4000, 4.766, cancel_wait_seconds=3.234)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_cancel_wait_that_exceeds_freshness_limit_rejects_stop(self):
        await self.interpret_after('STOP', 4000, 7.5, cancel_wait_seconds=1)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.bridge.log.assert_any_call('intent_rejected', commandId='fresh-voice', reason='expired_intent')

    async def test_fresh_cancel_wait_does_not_consume_action_duration(self):
        accepted_at = await self.interpret_after('FORWARD', 4000, 4.766, cancel_wait_seconds=1)
        self.bridge.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.bridge.arbiter.deadline, accepted_at + 4)

    async def test_cancel_wait_epoch_change_still_rejects_old_action(self):
        await self.interpret_after('FORWARD', 4000, .25, change_epoch=True)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.assertFalse(any(call.args[0] == 'intent_rejected'
                             and call.kwargs.get('commandId') == 'fresh-voice'
                             for call in self.bridge.log.call_args_list))

    async def test_cancel_wait_newer_intent_still_rejects_old_action(self):
        await self.interpret_after('FORWARD', 4000, .25, change_revision=True)
        self.bridge.adapter.send_action.assert_not_awaited()
        self.assertFalse(any(call.args[0] == 'intent_rejected'
                             and call.kwargs.get('commandId') == 'fresh-voice'
                             for call in self.bridge.log.call_args_list))


if __name__ == '__main__':
    unittest.main()
