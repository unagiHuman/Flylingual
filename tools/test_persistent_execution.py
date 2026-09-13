"""Bridge state/ordering regression tests with protocol stubs, not motion proof."""
import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.server import Bridge


def action(action='FORWARD', *, duration=None):
    return {'kind': 'action', 'action': action, 'plan': None, 'validForMs': duration,
            'reply': '', 'operation': 'new',
            'executionMode': 'until_next_command' if duration is None else 'timed',
            'targetExecutionId': None}


def update(target='move-1', *, operation='continue', mode='inherit', duration=None):
    return {'kind': 'update', 'action': None, 'plan': None, 'validForMs': duration,
            'reply': '', 'operation': operation, 'executionMode': mode,
            'targetExecutionId': target}


class PersistentExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 100.0
        self.counter = 0
        self.b = Bridge(copy.deepcopy(_DEFAULT))
        b = self.b
        b.log = Mock()
        b.emit = Mock()
        b.summary = Mock(return_value={'stale': False, 'interpretation': 'unknown'})
        b.control_ws = object()
        b.motor_writer = Mock()
        b.adapter = SimpleNamespace(connected=True, status={}, send_action=AsyncMock())
        b.conversation.state = 'live'
        b.conversation.append = AsyncMock()
        b.conversation.stop = AsyncMock()
        b.conversation_accepting = True
        b.native_voice_control = True
        b.arbiter.owner = 'gpt'
        b.arbiter.resume()
        b.voice_control_epoch = b.arbiter.epoch
        clock = SimpleNamespace(monotonic=lambda: self.now)
        for module in ('server', 'control', 'action_plans'):
            item = patch('Runtime.Bridge.' + module + '.time', clock)
            item.start()
            self.addCleanup(item.stop)
        self.observation()

    async def asyncTearDown(self):
        tasks = tuple(self.b.tasks | self.b.intent_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def observation(self, **changes):
        b = self.b
        value = {'type': 'local_safety_observation', 'controlEpoch': b.arbiter.epoch,
                 'conversationGeneration': b.conversation_generation,
                 'sequence': b.local_observation.sequence + 1, 'ageMs': 0,
                 'groundPresent': True, 'leftEdge': 'safe', 'rightEdge': 'safe',
                 'forwardBlocked': False, 'bodyUnsafe': False}
        value.update(changes)
        b.local_observation.accept(value)
        return value

    async def propose(self, proposal, command=None, side_effect=None):
        self.counter += 1
        command = command or 'proposal-' + str(self.counter)
        b = self.b
        b.conversation.interpret = AsyncMock(return_value=proposal, side_effect=side_effect)
        await b.player_intent('protocol-only instruction', command, b.arbiter.epoch,
                              b.intent_revision, 'delegation')
        return command

    async def start(self, duration=None):
        await self.propose(action(duration=duration), 'move-1')
        execution = self.b.active_execution
        self.assertIsNotNone(execution)
        # This is a protocol applied flag, not a fabricated BrainFrame or motor.
        self.b.requests[execution['requestId']]['applied'] = True
        return execution

    def rejected(self, reason):
        self.assertTrue(any(call.args[0].get('stage') == 'rejected'
                            and call.args[0].get('reason') == reason
                            for call in self.b.emit.call_args_list), reason)

    async def plan_state(self, duration=4000):
        b = self.b
        self.observation()
        with patch.object(b, 'task', side_effect=lambda coroutine: coroutine.close()):
            await b.plans.begin('right_then_forward', 'move-1', b.arbiter.epoch,
                                b.conversation_generation, duration,
                                intent_deadline=self.now + 8, revision=b.intent_revision,
                                execution_mode='timed' if duration is not None else 'until_next_command')
        plan = b.plans.active
        # Restore a running-forward scheduling state without running any body.
        plan.update(step=1, phaseSent=True, appliedAt=self.now - .1,
                    submittedAt=self.now - .2, applyDeadline=self.now + 11.8)
        b.update_execution_step('move-1', 'FORWARD', 1)
        request = await b.submit('FORWARD', 'gpt', plan['planId'] + '-1')
        plan['requestId'] = request
        b.requests[request]['applied'] = True
        return plan

    async def test_continuous_action_uses_one_request_and_survives_long_silence(self):
        execution = await self.start()
        for _ in range(60):
            self.now += 1
            await self.b.check_control_safety()
        self.assertIs(self.b.current_execution(), execution)
        self.assertIsNone(self.b.arbiter.deadline)
        self.b.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertIsNone(self.b.intent_context()['activeCommand']['remainingMs'])

    async def test_question_and_clarify_do_not_replace_or_resend(self):
        execution = await self.start()
        for kind in ('question', 'clarify'):
            proposal = action(duration=4000)
            proposal.update(kind=kind, action=None)
            self.b.intent_revision += 1
            await self.propose(proposal)
            self.assertIs(self.b.current_execution(), execution)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_stop_revokes_execution_before_transport_await(self):
        await self.start()
        previous = (self.b.arbiter.epoch, self.b.conversation_generation)

        async def sent(action_name, request):
            self.assertEqual(action_name, 'STOP')
            self.assertIsNone(self.b.current_execution())
            self.assertIsNone(self.b.active_execution)

        self.b.adapter.send_action.side_effect = sent
        await self.propose(action('STOP', duration=4000))
        self.assertEqual(previous, (self.b.arbiter.epoch, self.b.conversation_generation))
        self.assertTrue(self.b.can_keep_voice_listening())
        await self.propose(update())
        self.rejected('stale_execution')

    async def test_new_timed_command_replaces_continuous_and_does_not_restore_it(self):
        await self.start()
        await self.propose(action('TURN_L', duration=2000), 'turn-2')
        self.assertEqual(self.b.current_execution()['executionId'], 'turn-2')
        self.now += 2
        await self.b.check_control_safety()
        self.assertIsNone(self.b.active_execution)
        self.assertEqual([call.args[0] for call in self.b.adapter.send_action.call_args_list],
                         ['FORWARD', 'TURN_L', 'STOP'])
        self.now += 20
        await self.b.check_control_safety()
        self.assertIsNone(self.b.current_execution())

    async def test_continue_inherits_exact_deadline_without_submit(self):
        execution = await self.start(duration=8000)
        self.now += 3
        await self.propose(update())
        self.assertIs(self.b.current_execution(), execution)
        self.assertEqual(execution['deadline'], 108)
        self.assertEqual(self.b.arbiter.deadline, 108)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_explicit_time_changes_do_not_submit_another_action(self):
        execution = await self.start(duration=8000)
        await self.propose(update(mode='until_next_command'))
        self.assertIsNone(execution['deadline'])
        self.now += 20
        await self.propose(update(mode='timed', duration=3000))
        self.assertEqual(execution['deadline'], 123)
        self.assertEqual(self.b.arbiter.deadline, 123)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_conditions_add_monitoring_without_changing_action_request_or_deadline(self):
        execution = await self.start(duration=8000)
        before = (execution['action'], execution['requestId'], execution['deadline'])
        self.now += 2
        self.observation()
        await self.propose(update(operation='modify_conditions'))
        self.assertTrue(execution['monitorHazards'])
        self.assertEqual(before, (execution['action'], execution['requestId'], execution['deadline']))
        self.b.adapter.send_action.assert_awaited_once()
        self.observation(forwardBlocked=True)
        await self.b.check_control_safety()
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.arbiter.reason, 'forward_blocked')

    async def test_missing_conditions_observation_stops_existing_movement(self):
        await self.start()
        self.b.local_observation.clear()
        await self.propose(update(operation='modify_conditions'))
        self.rejected('local_observation_unavailable')
        self.assertIsNone(self.b.active_execution)
        self.assertTrue(self.b.arbiter.inhibited)

    async def test_conditional_observation_expiry_stops_without_expiring_brain(self):
        await self.start()
        await self.propose(update(operation='modify_conditions'))
        self.now += .75
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'local_observation_unavailable')
        self.assertIsNone(self.b.active_execution)

    async def test_plan_update_preserves_completed_turn_and_all_phase_clocks(self):
        plan = await self.plan_state()
        before = dict(plan)
        self.now += 1
        self.observation()
        await self.propose(update(operation='modify_conditions'))
        self.assertEqual(plan, before)
        await self.propose(update(mode='until_next_command'))
        self.assertEqual(plan, {**before, 'deadline': None, 'executionMode': 'until_next_command'})
        self.b.adapter.send_action.assert_awaited_once_with('FORWARD', 1)

    async def test_nudge_update_cannot_become_unbounded(self):
        execution = await self.start(duration=4000)
        execution['plan'] = 'nudge_right'
        await self.propose(update(mode='until_next_command'))
        self.rejected('cannot_extend_nudge')
        self.assertEqual(execution['deadline'], 104)

    async def test_update_context_cannot_name_an_execution_not_observed_at_start(self):
        await self.start()

        async def interpret(*_):
            self.b.activate_execution('other', 'TURN_L', 'until_next_command', None)
            return update(target='other')

        await self.propose(update(target='other'), side_effect=interpret)
        self.rejected('stale_execution')
        self.assertEqual(self.b.current_execution()['executionId'], 'other')

    async def test_replacement_while_interpreting_rejects_old_target(self):
        await self.start()

        async def interpret(*_):
            self.b.activate_execution('other', 'TURN_L', 'until_next_command', None)
            return update()

        await self.propose(update(), side_effect=interpret)
        self.rejected('stale_execution')
        self.assertEqual(self.b.current_execution()['executionId'], 'other')

    async def test_stop_while_interpreting_update_cannot_restore_old_execution(self):
        await self.start()

        async def interpret(*_):
            await self.b.submit('STOP', 'safety', 'concurrent-stop')
            return update()

        await self.propose(update(), side_effect=interpret)
        self.rejected('stale_execution')
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.request_counter, 2)

    async def test_expiry_during_interpretation_cannot_be_extended(self):
        await self.start(duration=1000)

        async def interpret(*_):
            self.now += 1
            return update(mode='until_next_command')

        await self.propose(update(), side_effect=interpret)
        self.rejected('stale_execution')
        await self.b.check_control_safety()
        self.assertIsNone(self.b.active_execution)

    async def test_phase_change_during_interpretation_uses_latest_phase(self):
        plan = await self.plan_state()
        # Start the classifier while TURN_R is still the active requested phase.
        self.b.active_execution.update(action='TURN_R', step=0)

        async def interpret(*_):
            self.b.active_execution.update(action='FORWARD', step=1)
            return update()

        await self.propose(update(), side_effect=interpret)
        self.assertEqual(self.b.current_execution()['action'], 'FORWARD')
        self.assertEqual(plan['step'], 1)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_brain_stale_clears_continuous_and_resume_does_not_restore_it(self):
        await self.start()
        self.b.summary.return_value['stale'] = True
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'stale_brain')
        self.assertIsNone(self.b.active_execution)
        self.b.summary.return_value['stale'] = False
        self.b.arbiter.resume()
        self.assertIsNone(self.b.intent_context()['activeCommand'])

    async def test_epoch_or_generation_change_invalidates_context(self):
        for attribute, field in ((self.b.arbiter, 'epoch'), (self.b, 'conversation_generation')):
            await self.start()
            setattr(attribute, field, getattr(attribute, field) + 1)
            self.assertIsNone(self.b.current_execution())
            await self.b.check_control_safety()
            self.assertEqual(self.b.arbiter.reason, 'execution_context_lost')
            self.assertIsNone(self.b.active_execution)
            self.b.arbiter.resume()
            self.b.voice_control_epoch = self.b.arbiter.epoch
            self.b.arbiter.seen.clear()

    async def test_rejected_or_superseded_request_is_not_an_active_reference(self):
        execution = await self.start()
        request = self.b.requests[execution['requestId']]
        for flag in ('rejected', 'superseded'):
            request[flag] = True
            self.assertIsNone(self.b.current_execution())
            request.pop(flag)
        request['rejected'] = True
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'execution_not_applied')

    async def test_continuous_action_still_has_finite_application_wait(self):
        await self.propose(action(), 'move-1')
        self.now += self.b.config['control']['stopTimeoutMs'] / 1000
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'execution_apply_timeout')
        self.assertIsNone(self.b.active_execution)

    async def test_live_receives_request_changes_without_periodic_renewal(self):
        execution = await self.start()
        b = self.b
        b.conversation.append.reset_mock()
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 1)
        channel, content = b.conversation.append.await_args.args
        self.assertEqual(channel, 'thinking')
        self.assertIn('until_next_command', content)
        self.assertIn('not proof of movement', content)
        self.assertLessEqual(len(content), 380)
        self.now += 2
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 1)
        b.clear_execution('stop')
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 2)
        self.assertIn('"activeRequest":null', b.conversation.append.await_args.args[1])
        self.assertEqual(b.adapter.send_action.await_count, 1)

    async def test_live_context_waits_for_execution_and_reports_real_application(self):
        b = self.b
        b.conversation.append.reset_mock()
        b.publish_execution_context()
        await asyncio.sleep(0)
        b.conversation.append.assert_not_awaited()
        await self.propose(action(), 'move-1')
        b.conversation.append.reset_mock()
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertIn('"brainApplied":false', b.conversation.append.await_args.args[1])
        b.requests[b.active_execution['requestId']]['applied'] = True
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 2)
        self.assertIn('"brainApplied":true', b.conversation.append.await_args.args[1])
        self.assertEqual(b.adapter.send_action.await_count, 1)

    async def test_live_context_phase_change_is_complete_and_chat_only_is_excluded(self):
        execution = await self.start()
        b = self.b
        execution.update(plan='right_then_forward', monitorHazards=True, step=0, action='TURN_R')
        b.conversation.append.reset_mock()
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertLessEqual(len(b.conversation.append.await_args.args[1]), 380)
        execution.update(step=1, action='FORWARD')
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 2)
        self.assertIn('"step":1', b.conversation.append.await_args.args[1])
        b.conversation_interaction = 'chat_only'
        b.clear_execution('test')
        b.publish_execution_context()
        await asyncio.sleep(0)
        self.assertEqual(b.conversation.append.await_count, 2)

    async def test_duplicate_update_does_not_extend_deadline_twice(self):
        execution = await self.start()
        await self.propose(update(mode='timed', duration=4000), 'same-update')
        self.now += 2
        await self.propose(update(mode='timed', duration=4000), 'same-update')
        self.rejected('duplicate_command')
        self.assertEqual(execution['deadline'], 104)

    async def application_request(self, action_name='FORWARD', delegation='original-delegation'):
        request_id = await self.b.submit(action_name, 'gpt', 'application-test', delegation_id=delegation)
        self.b.conversation.append.reset_mock()
        return request_id, self.b.requests[request_id]

    async def test_application_notice_waits_for_applied_and_uses_original_delegation_once(self):
        request_id, item = await self.application_request()
        b = self.b
        self.assertEqual(item['delegationId'], 'original-delegation')
        self.assertEqual(item['conversationGeneration'], b.conversation_generation)
        self.assertEqual(item['contextGeneration'], b.conversation.context_generation)
        await b.notify_application(request_id, item)
        b.conversation.append.assert_not_awaited()
        self.assertFalse(item.get('applicationNoticeSent', False))
        item['applied'] = True
        await b.notify_application(request_id, item)
        await b.notify_application(request_id, item)
        b.conversation.append.assert_awaited_once()
        args = b.conversation.append.await_args.args
        self.assertEqual(args[0], 'thinking')
        self.assertEqual(args[2], 'original-delegation')
        self.assertIn('FORWARD', args[1])
        self.assertTrue(item['applicationNoticeSent'])

    async def test_application_notice_deduplicates_before_awaiting_reply_transport(self):
        request_id, item = await self.application_request()
        item['applied'] = True
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_append(*_):
            entered.set()
            await release.wait()

        self.b.conversation.append.side_effect = blocked_append
        first = asyncio.create_task(self.b.notify_application(request_id, item))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await self.b.notify_application(request_id, item)
            self.b.conversation.append.assert_awaited_once()
        finally:
            release.set()
            await first

    async def test_old_application_notice_is_silent_after_each_generation_changes(self):
        request_id, item = await self.application_request()
        item['applied'] = True
        for target, field in ((self.b.arbiter, 'epoch'), (self.b, 'conversation_generation'),
                              (self.b.conversation, 'context_generation')):
            with self.subTest(field=field):
                before = getattr(target, field)
                setattr(target, field, before + 1)
                await self.b.notify_application(request_id, item)
                self.b.conversation.append.assert_not_awaited()
                setattr(target, field, before)
        self.assertFalse(item.get('applicationNoticeSent', False))

    async def test_new_request_prevents_old_application_notice_even_without_superseded_flag(self):
        request_id, item = await self.application_request()
        item['applied'] = True
        await self.b.submit('STOP', 'gpt', 'new-stop', delegation_id='stop-delegation')
        self.assertGreater(self.b.request_counter, request_id)
        self.assertFalse(item.get('superseded', False))
        await self.b.notify_application(request_id, item)
        self.b.conversation.append.assert_not_awaited()

    async def test_rejected_or_superseded_application_notice_is_not_sent(self):
        request_id, item = await self.application_request()
        item['applied'] = True
        for flag in ('rejected', 'superseded'):
            with self.subTest(flag=flag):
                item[flag] = True
                await self.b.notify_application(request_id, item)
                self.b.conversation.append.assert_not_awaited()
                item.pop(flag)

    async def test_application_notice_requires_live_uninhibited_gpt_control(self):
        request_id, item = await self.application_request()
        item['applied'] = True
        changes = ((self.b, 'conversation_accepting', False),
                   (self.b, 'conversation_interaction', 'chat_only'),
                   (self.b.conversation, 'state', 'off'),
                   (self.b.arbiter, 'inhibited', True),
                   (self.b.arbiter, 'owner', 'observer'))
        for target, field, invalid in changes:
            with self.subTest(field=field):
                before = getattr(target, field)
                setattr(target, field, invalid)
                await self.b.notify_application(request_id, item)
                self.b.conversation.append.assert_not_awaited()
                setattr(target, field, before)

    async def test_application_without_original_delegation_has_no_notice(self):
        request_id, item = await self.application_request(delegation=None)
        item['applied'] = True
        await self.b.notify_application(request_id, item)
        self.b.conversation.append.assert_not_awaited()

    async def test_voice_proposal_carries_its_delegation_through_submission(self):
        await self.propose(action(), 'voice-application-test')
        self.assertEqual(self.b.requests[self.b.request_counter]['delegationId'], 'delegation')

    async def test_brain_frame_completes_original_voice_request_once(self):
        await self.propose(action(), 'voice-application-test')
        b = self.b
        b.conversation.append.assert_not_awaited()
        frame = {'type': 'brain_frame', 'sequence': 12, 'appliedRequestId': b.request_counter}
        await b.brain_message(frame)
        await asyncio.sleep(0)
        await b.brain_message({**frame, 'sequence': 13})
        await asyncio.sleep(0)
        b.conversation.append.assert_awaited_once()
        self.assertEqual(b.conversation.append.await_args.args[2], 'delegation')
        self.assertLessEqual(len(b.conversation.append.await_args.args[1]), 380)


if __name__ == '__main__':
    unittest.main()
