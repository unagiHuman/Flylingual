"""Offline plan admission contracts, not Unity sensors or Brain/motion acceptance."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.action_plans import BoundedPlanRunner, LocalSafetyObservation
from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlArbiter, ControlError
from Runtime.Bridge.server import Bridge


class BoundedPlanAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = SimpleNamespace(now=104.766)
        self.clock.monotonic = lambda: self.clock.now
        config = copy.deepcopy(_DEFAULT)
        arbiter = ControlArbiter(config['control'])
        arbiter.owner = 'gpt'
        arbiter.resume()
        self.bridge = SimpleNamespace(
            config=config, arbiter=arbiter, intent_revision=2, conversation_generation=3,
            closed=False, control_ws=object(), switching=False, release_unknown=False,
            conversation_accepting=True, conversation=SimpleNamespace(state='live'),
            conversation_interaction='control', adapter=SimpleNamespace(connected=True),
            summary=Mock(return_value={'stale': False}), local_observation=LocalSafetyObservation(),
            log=Mock(), inhibit=AsyncMock(), task=Mock(side_effect=self.close_unscheduled_run),
            activate_execution=Mock(), update_execution_step=Mock())
        self.runner = BoundedPlanRunner(self.bridge)
        self.refresh_observation()
        self.time_patch = patch('Runtime.Bridge.action_plans.time', self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    @staticmethod
    def close_unscheduled_run(coroutine):
        # Only admission is under test. Never fabricate applied Brain frames or run motors.
        coroutine.close()
        return None

    def refresh_observation(self):
        b = self.bridge
        b.local_observation.accept({
            'type': 'local_safety_observation', 'controlEpoch': b.arbiter.epoch,
            'conversationGeneration': b.conversation_generation,
            'sequence': b.local_observation.sequence + 1, 'ageMs': 0,
            'groundPresent': True, 'leftEdge': 'safe', 'rightEdge': 'safe',
            'forwardBlocked': False, 'bodyUnsafe': False}, now=self.clock.now)

    async def begin(self, duration=4000, **overrides):
        b = self.bridge
        args = dict(name='right_then_forward', command_id='proposal', epoch=b.arbiter.epoch,
                    generation=b.conversation_generation, duration_ms=duration,
                    intent_deadline=108.0, revision=b.intent_revision)
        args.update(overrides)
        await self.runner.begin(**args)

    def cancellation(self, elapsed=0, mutate=None, refresh=True):
        async def wait():
            self.clock.now += elapsed
            self.runner.active = None
            if mutate:
                mutate()
            if refresh:
                self.refresh_observation()
        self.runner.cancel_and_wait = AsyncMock(side_effect=wait)

    async def test_4766ms_interpretation_keeps_full_plan_duration(self):
        await self.begin()
        self.assertEqual(self.runner.active['deadline'], 108.766)
        self.bridge.task.assert_called_once()

    async def test_fresh_cancellation_wait_does_not_consume_plan_duration(self):
        self.cancellation(elapsed=1)
        await self.begin()
        self.assertEqual(self.runner.active['deadline'], self.clock.now + 4)

    async def test_just_before_intent_deadline_accepts_full_duration(self):
        self.clock.now = 107.999
        self.refresh_observation()
        await self.begin()
        self.assertEqual(self.runner.active['deadline'], 111.999)

    async def test_exact_and_later_intent_deadline_rejected_before_cancellation(self):
        self.runner.cancel_and_wait = AsyncMock()
        for now in (108.0, 108.001):
            with self.subTest(now=now):
                self.clock.now = now
                self.refresh_observation()
                with self.assertRaisesRegex(ControlError, '^expired_intent$'):
                    await self.begin()
        self.runner.cancel_and_wait.assert_not_awaited()
        self.bridge.task.assert_not_called()

    async def test_cancellation_wait_rechecks_intent_deadline(self):
        self.clock.now = 104.5
        self.refresh_observation()
        self.cancellation(elapsed=3.5)
        with self.assertRaisesRegex(ControlError, '^expired_intent$'):
            await self.begin()
        self.bridge.task.assert_not_called()

    async def test_failed_replacement_still_inhibits(self):
        self.runner.active = {'planId': 'old-plan'}
        self.cancellation(elapsed=4)
        with self.assertRaisesRegex(ControlError, '^expired_intent$'):
            await self.begin()
        self.bridge.inhibit.assert_awaited_once_with('plan_replacement_failed')
        self.bridge.task.assert_not_called()

    async def test_cancel_wait_rechecks_epoch_generation_and_revision(self):
        b = self.bridge
        for target, field, reason in ((b.arbiter, 'epoch', 'plan_old_generation'),
                                      (b, 'conversation_generation', 'plan_old_generation'),
                                      (b, 'intent_revision', 'stale_intent')):
            with self.subTest(field=field):
                self.cancellation(mutate=lambda: setattr(target, field, getattr(target, field) + 1))
                with self.assertRaisesRegex(ControlError, '^' + reason + '$'):
                    await self.begin()
        self.bridge.task.assert_not_called()

    async def test_old_revision_is_rejected_before_cancel(self):
        self.runner.cancel_and_wait = AsyncMock()
        with self.assertRaisesRegex(ControlError, '^stale_intent$'):
            await self.begin(revision=1)
        self.runner.cancel_and_wait.assert_not_awaited()

    async def test_zero_excessive_and_noninteger_durations_remain_rejected(self):
        for duration in (0, -1, 8001, True, 4000.0):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(ControlError, '^invalid_command_duration$'):
                    await self.begin(duration)
        self.bridge.task.assert_not_called()

    async def test_missing_observation_still_blocks_plan(self):
        self.bridge.local_observation.clear()
        with self.assertRaisesRegex(ControlError, '^local_observation_unavailable$'):
            await self.begin()
        self.bridge.task.assert_not_called()

    async def test_observation_expiring_during_cancellation_still_blocks_plan(self):
        self.cancellation(elapsed=.75, refresh=False)
        with self.assertRaisesRegex(ControlError, '^local_observation_unavailable$'):
            await self.begin()
        self.bridge.task.assert_not_called()

    async def test_unknown_and_hazard_observations_still_block_plan(self):
        for field, value, reason in (('leftEdge', 'unknown', 'local_observation_unknown'),
                                     ('rightEdge', 'near', 'edge_near'),
                                     ('groundPresent', False, 'ground_missing'),
                                     ('forwardBlocked', True, 'forward_blocked'),
                                     ('bodyUnsafe', True, 'body_unsafe')):
            with self.subTest(field=field):
                self.refresh_observation()
                self.bridge.local_observation.sample[field] = value
                with self.assertRaisesRegex(ControlError, '^' + reason + '$'):
                    await self.begin()
        self.bridge.task.assert_not_called()


class BridgePlanFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_passes_independent_intent_deadline_and_full_plan_duration(self):
        b = Bridge(copy.deepcopy(_DEFAULT))
        b.log = Mock()
        b.summary = Mock(return_value={'stale': False})
        b.conversation.append = AsyncMock()
        b.plans.begin = AsyncMock()
        b.voice_control_epoch = b.arbiter.epoch
        clock = SimpleNamespace(now=100.0)
        clock.monotonic = lambda: clock.now

        async def interpret(*_):
            clock.now += 4.766
            return {'kind': 'plan', 'action': None, 'plan': 'nudge_right',
                    'validForMs': 4000, 'reply': ''}

        b.conversation.interpret = AsyncMock(side_effect=interpret)
        with patch('Runtime.Bridge.server.time', clock):
            await b.player_intent('protocol request', 'plan-intent', b.arbiter.epoch,
                                  b.intent_revision, 'delegation')
        b.plans.begin.assert_awaited_once_with('nudge_right', 'plan-intent', b.arbiter.epoch,
            b.conversation_generation, 4000, intent_deadline=108.0, revision=b.intent_revision,
            execution_mode='timed', delegation_id='delegation')


if __name__ == '__main__':
    unittest.main()
