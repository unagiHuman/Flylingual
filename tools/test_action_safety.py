"""Action-specific local safety contracts; no API, Brain, Unity or motor run."""
import unittest
from unittest.mock import AsyncMock

from Runtime.Bridge.action_plans import LocalSafetyObservation
from Runtime.Bridge.control import ControlError
from tools import test_persistent_plan_runner as helpers


def observation(sequence=1, **changes):
    event = {'type': 'local_safety_observation', 'controlEpoch': 1,
             'conversationGeneration': 3, 'sequence': sequence, 'ageMs': 0,
             'groundPresent': True, 'leftEdge': 'safe', 'rightEdge': 'safe',
             'forwardBlocked': True, 'bodyUnsafe': False,
             'travelMeters': 0, 'horizontalSpeedMetersPerSecond': 0}
    event.update(changes)
    return event


class ActionSafetyObservationTests(unittest.TestCase):
    def test_only_pure_turns_ignore_forward_obstacle(self):
        value = LocalSafetyObservation()
        value.accept(observation(), now=100)
        for action in ('TURN_R', 'TURN_L'):
            self.assertIsNone(value.concern(100, action=action))
        for action in (None, 'FORWARD', 'FORWARD_R', 'FORWARD_L', 'STOP', 'unknown'):
            self.assertEqual(value.concern(100, action=action), 'forward_blocked')
        self.assertEqual(value.summary(100)['concern'], 'forward_blocked')

    def test_turns_ignore_ground_and_edge_warnings_but_require_safe_body(self):
        for field, change, reason in (('bodyUnsafe', True, 'body_unsafe'),):
            value = LocalSafetyObservation()
            value.accept(observation(**{field: change}), now=100)
            for action in ('TURN_R', 'TURN_L'):
                with self.subTest(field=field, action=action):
                    self.assertEqual(value.concern(100, action=action), reason)
        for field, change in (('groundPresent', False), ('leftEdge', 'unknown'),
                              ('rightEdge', 'unknown'), ('leftEdge', 'near'),
                              ('rightEdge', 'very_near')):
            value = LocalSafetyObservation()
            value.accept(observation(**{field: change}), now=100)
            with self.subTest(field=field):
                self.assertIsNone(value.concern(100, action='TURN_R'))

    def test_turns_still_require_fresh_observation(self):
        value = LocalSafetyObservation()
        self.assertEqual(value.concern(100, action='TURN_R'), 'local_observation_unavailable')
        value.accept(observation(), now=100)
        self.assertIsNone(value.concern(100.749, action='TURN_R'))
        self.assertEqual(value.concern(100.75, action='TURN_L'), 'local_observation_unavailable')

    def test_distance_admission_remains_strictly_forward_safe(self):
        value = LocalSafetyObservation()
        value.accept(observation(), now=100)
        with self.assertRaisesRegex(ControlError, '^forward_blocked$'):
            value.require_distance(100)


class ActionSafetyPlanTests(unittest.IsolatedAsyncioTestCase):
    begin = helpers.PersistentPlanRunnerTests.begin
    run_for = helpers.PersistentPlanRunnerTests.run_for

    async def asyncSetUp(self):
        await helpers.PersistentPlanRunnerTests.asyncSetUp(self)
        self.b.local_observation = LocalSafetyObservation()
        self.refresh()
        self.tick = self.refresh

    def refresh(self, **changes):
        value = self.b.local_observation
        value.accept(observation(value.sequence + 1, **changes), now=self.now)

    async def test_nudge_turn_is_admitted_and_finishes_with_obstacle_ahead(self):
        plan = await self.begin(name='nudge_right', duration=4000, mode='timed')
        await self.run_for(plan, 2)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R'])
        self.b.finish_plan.assert_awaited_once_with(plan, 'plan_finished')
        self.b.inhibit.assert_not_awaited()

    async def test_turn_then_forward_checks_obstacle_before_any_forward_submission(self):
        plan = await self.begin(name='right_then_forward')
        await self.run_for(plan, 2)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R'])
        self.assertEqual(plan['step'], 1)
        self.b.inhibit.assert_awaited_once_with('forward_blocked')
        self.b.finish_plan.assert_not_awaited()

    async def test_cleared_obstacle_allows_forward_after_the_turn(self):
        plan = await self.begin(name='left_then_forward')
        self.tick = lambda: self.refresh(forwardBlocked=self.now < 100.2)
        await self.run_for(plan, 1.5)
        self.assertEqual([x[0] for x in self.sent], ['TURN_L', 'FORWARD'])
        self.b.inhibit.assert_not_awaited()

    async def test_obstacle_appearing_at_phase_boundary_blocks_forward(self):
        self.refresh(forwardBlocked=False)
        plan = await self.begin(name='right_then_forward')
        self.tick = lambda: self.refresh(forwardBlocked=self.now >= 100.5)
        await self.run_for(plan, 2)
        self.assertEqual([x[0] for x in self.sent], ['TURN_R'])
        self.b.inhibit.assert_awaited_once_with('forward_blocked')

    async def test_forward_only_plan_rejects_obstacle_before_cancelling_existing_plan(self):
        self.runner.cancel_and_wait = AsyncMock()
        with self.assertRaisesRegex(ControlError, '^forward_blocked$'):
            await self.begin(name='forward_until_concern')
        self.runner.cancel_and_wait.assert_not_awaited()
        self.b.activate_execution.assert_not_called()

    async def test_turn_admission_rechecks_body_safety_after_cancellation(self):
        async def changed():
            self.refresh(bodyUnsafe=True)
        self.runner.cancel_and_wait = AsyncMock(side_effect=changed)
        with self.assertRaisesRegex(ControlError, '^body_unsafe$'):
            await self.begin(name='nudge_left', duration=4000, mode='timed')
        self.b.activate_execution.assert_not_called()

    async def test_guard_without_action_preserves_old_strict_behavior(self):
        self.assertEqual(self.runner.guard(1, 3, None), 'forward_blocked')
        self.assertIsNone(self.runner.guard(1, 3, None, action='TURN_L'))


if __name__ == '__main__':
    unittest.main()
