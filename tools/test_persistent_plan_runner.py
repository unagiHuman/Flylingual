"""Offline scheduling/schema contracts; no Unity, Brain or API execution."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.action_plans import BoundedPlanRunner, validate_intent
from Runtime.Bridge.control import ControlError


class PersistentProposalTests(unittest.TestCase):
    def proposal(self, **changes):
        value = {'kind': 'action', 'action': 'FORWARD', 'plan': None, 'validForMs': None,
                 'reply': '', 'operation': 'new', 'executionMode': 'until_next_command',
                 'targetExecutionId': None}
        value.update(changes)
        return value

    def test_continuous_action_and_plan_accept_null_duration(self):
        for changes in ({}, {'kind': 'plan', 'action': None, 'plan': 'right_then_forward'}):
            item = self.proposal(**changes)
            self.assertIs(validate_intent(item, 8000), item)

    def test_legacy_bounded_shape_stays_compatible(self):
        item = {'kind': 'action', 'action': 'FORWARD', 'plan': None, 'validForMs': 4000, 'reply': ''}
        self.assertIs(validate_intent(item, 8000), item)

    def test_update_modes_and_condition_inheritance(self):
        for operation, mode, duration in (
                ('continue', 'inherit', None), ('continue', 'until_next_command', None),
                ('continue', 'timed', 8000), ('modify_conditions', 'inherit', None)):
            item = self.proposal(kind='update', action=None, operation=operation,
                                 executionMode=mode, validForMs=duration, targetExecutionId='active-1')
            self.assertIs(validate_intent(item, 8000), item)

    def test_invalid_combinations_cannot_gain_continuous_authority(self):
        invalid = [
            {'action': 'STOP'},
            {'kind': 'plan', 'action': None, 'plan': 'nudge_right'},
            {'kind': 'question', 'action': None}, {'kind': 'clarify', 'action': None},
            {'executionMode': 'inherit'}, {'validForMs': 8000},
            {'executionMode': 'timed'}, {'executionMode': 'timed', 'validForMs': True},
            {'executionMode': 'timed', 'validForMs': 8001},
            {'executionMode': 'timed', 'validForMs': 0},
            {'operation': 'continue'}, {'targetExecutionId': 'other'},
            {'kind': 'update', 'action': None, 'operation': 'new', 'targetExecutionId': 'a'},
            {'kind': 'update', 'action': None, 'operation': 'continue'},
            {'kind': 'update', 'action': None, 'operation': 'continue', 'targetExecutionId': ' '},
            {'kind': 'update', 'action': None, 'operation': 'continue', 'targetExecutionId': 'a' * 129},
            {'kind': 'update', 'operation': 'continue', 'targetExecutionId': 'a'},
            {'kind': 'update', 'action': None, 'operation': 'modify_conditions', 'targetExecutionId': 'a'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ControlError):
                validate_intent(self.proposal(**changes), 8000)

    def test_partial_extension_and_extra_fields_rejected(self):
        for item in (self.proposal(extra=True), {k: v for k, v in self.proposal().items() if k != 'operation'}):
            with self.assertRaises(ControlError):
                validate_intent(item, 8000)


class PersistentPlanRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 100.0
        self.until = 101.0
        self.tick = None
        self.auto_applied = True
        self.sent = []
        self.b = SimpleNamespace(
            config={'control': {'maxActionMs': 8000, 'stopTimeoutMs': 12000}},
            arbiter=SimpleNamespace(owner='gpt', inhibited=False, epoch=1, accept=Mock()),
            intent_revision=2, conversation_generation=3, closed=False, control_ws=object(),
            switching=False, release_unknown=False, conversation_accepting=True,
            conversation=SimpleNamespace(state='live'), conversation_interaction='control',
            adapter=SimpleNamespace(connected=True), summary=Mock(return_value={'stale': False}),
            local_observation=SimpleNamespace(concern=Mock(return_value=None)),
            requests={}, log=Mock(), activate_execution=Mock(), update_execution_step=Mock(),
            task=Mock(side_effect=lambda coroutine: coroutine.close()))
        self.runner = BoundedPlanRunner(self.b)

        async def submit(action, source, command_id):
            request = len(self.sent) + 1
            self.sent.append((action, self.now))
            self.b.requests[request] = {'applied': self.auto_applied}
            return request

        async def stop(*_):
            self.runner.cancel()

        async def sleep(seconds):
            self.now += seconds
            if self.tick:
                self.tick()
            if self.now >= self.until:
                self.runner.cancel()

        self.b.submit = AsyncMock(side_effect=submit)
        self.b.inhibit = AsyncMock(side_effect=stop)
        self.b.finish_plan = AsyncMock(side_effect=stop)
        self.time_patch = patch('Runtime.Bridge.action_plans.time', SimpleNamespace(monotonic=lambda: self.now))
        self.async_patch = patch('Runtime.Bridge.action_plans.asyncio', SimpleNamespace(
            sleep=sleep, wait_for=asyncio.wait_for, current_task=asyncio.current_task,
            gather=asyncio.gather, CancelledError=asyncio.CancelledError,
            TimeoutError=asyncio.TimeoutError))
        self.time_patch.start()
        self.async_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.async_patch.stop)

    async def begin(self, name='right_then_forward', duration=None, mode='until_next_command'):
        await self.runner.begin(name, 'execution-1', 1, 3, duration,
                                intent_deadline=108, revision=2, execution_mode=mode)
        return self.runner.active

    async def run_for(self, plan, seconds):
        self.until = self.now + seconds
        await self.runner.run(plan, 1, 3)

    async def test_indefinite_turn_runs_once_then_forward_beyond_old_maximum(self):
        plan = await self.begin()
        await self.run_for(plan, 24)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R', 'FORWARD'])
        self.assertEqual(plan['step'], 1)
        self.assertIsNone(plan['deadline'])
        self.assertLessEqual(self.sent[1][1] - self.sent[0][1], .551)
        self.b.inhibit.assert_not_awaited()
        self.b.finish_plan.assert_not_awaited()
        for call in self.b.arbiter.accept.call_args_list:
            self.assertIsNone(call.args[4])
            self.assertEqual(call.kwargs['execution_mode'], 'until_next_command')

    async def test_new_intent_revision_does_not_restart_running_plan(self):
        plan = await self.begin()
        self.tick = lambda: setattr(self.b, 'intent_revision', self.b.intent_revision + 1)
        await self.run_for(plan, 10)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R', 'FORWARD'])
        self.b.inhibit.assert_not_awaited()

    async def test_in_place_duration_change_preserves_phase_and_applied_clock(self):
        plan = await self.begin()
        original_applied = []

        def change_mode():
            if self.now >= 100.25 and not original_applied:
                original_applied.append(plan['appliedAt'])
                plan['executionMode'] = 'timed'
                plan['deadline'] = self.now + 2

        self.tick = change_mode
        await self.run_for(plan, 5)
        self.assertEqual(original_applied, [100.0])
        self.assertEqual([x[0] for x in self.sent], ['TURN_R', 'FORWARD'])
        self.assertLessEqual(self.sent[1][1], 100.551)
        self.b.finish_plan.assert_awaited_once_with(plan, 'plan_expired')

    async def test_timed_deadline_is_not_extended_by_phase_transition(self):
        plan = await self.begin(duration=1000, mode='timed')
        await self.run_for(plan, 5)
        self.assertEqual(plan['deadline'], 101)
        self.b.finish_plan.assert_awaited_once_with(plan, 'plan_expired')
        self.assertLess(self.b.arbiter.accept.call_args_list[1].args[4], 501)

    async def test_nudge_cannot_be_infinite_and_timed_nudge_finishes_once(self):
        with self.assertRaises(ControlError):
            await self.begin(name='nudge_left')
        plan = await self.begin(name='nudge_left', duration=4000, mode='timed')
        await self.run_for(plan, 5)
        self.assertEqual([x[0] for x in self.sent], ['TURN_L'])
        self.b.finish_plan.assert_awaited_once_with(plan, 'plan_finished')

    async def test_unapplied_turn_times_out_without_forward(self):
        self.auto_applied = False
        plan = await self.begin()
        await self.run_for(plan, 20)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R'])
        self.b.inhibit.assert_awaited_once_with('plan_apply_timeout')

    async def test_ack_without_apply_does_not_advance_phase(self):
        self.auto_applied = False
        plan = await self.begin()
        self.tick = lambda: self.b.requests[1].update(acked=True)
        await self.run_for(plan, 20)
        self.assertEqual(plan['step'], 0)
        self.b.inhibit.assert_awaited_once_with('plan_apply_timeout')

    async def test_second_phase_has_its_own_finite_application_timeout(self):
        plan = await self.begin()

        def disable_next_apply():
            self.auto_applied = False

        self.tick = disable_next_apply
        await self.run_for(plan, 20)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R', 'FORWARD'])
        self.assertGreater(plan['applyDeadline'], 112)
        self.b.inhibit.assert_awaited_once_with('plan_apply_timeout')

    async def test_submission_timeout_inhibits(self):
        plan = await self.begin()

        async def timeout(coroutine, seconds):
            coroutine.close()
            self.assertEqual(seconds, 12)
            raise asyncio.TimeoutError

        with patch('Runtime.Bridge.action_plans.asyncio.wait_for', side_effect=timeout):
            await self.run_for(plan, 20)
        self.b.inhibit.assert_awaited_once_with('plan_submit_timeout')

    async def test_hazard_stops_continuous_plan_without_new_action(self):
        plan = await self.begin()

        def hazard():
            self.b.local_observation.concern.return_value = 'forward_blocked'

        self.tick = hazard
        await self.run_for(plan, 20)
        self.b.inhibit.assert_awaited_once_with('forward_blocked')
        self.assertEqual(len(self.sent), 1)

    async def test_cancel_during_turn_never_submits_old_forward(self):
        plan = await self.begin()
        self.tick = self.runner.cancel
        await self.run_for(plan, 10)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R'])

    async def test_epoch_change_stops_continuous_plan(self):
        plan = await self.begin()
        self.tick = lambda: setattr(self.b.arbiter, 'epoch', 2)
        await self.run_for(plan, 10)
        self.b.inhibit.assert_awaited_once_with('plan_old_generation')


if __name__ == '__main__':
    unittest.main()
