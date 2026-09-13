"""Distance intent/odometry/STOP protocol tests; no API, Brain or Unity run."""
import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch

from Runtime.Bridge.action_plans import LocalSafetyObservation, validate_intent
from Runtime.Bridge.brain_adapter import BrainAdapterError
from Runtime.Bridge.control import ControlArbiter, ControlError
from tools import test_persistent_execution as helpers


def distance_action(meters=5, action='FORWARD'):
    result = helpers.action(action)
    result.update(executionMode='distance', distanceMeters=meters)
    return result


def distance_plan(meters=5, name='right_then_forward'):
    result = distance_action(meters)
    result.update(kind='plan', action=None, plan=name)
    return result


def distance_update(meters=5, target='move-1'):
    result = helpers.update(target, mode='distance')
    result['distanceMeters'] = meters
    return result


class DistanceSchemaTests(unittest.TestCase):
    def test_distance_action_plan_and_update_contract(self):
        for meters in (.05, 1, 100):
            for result in (distance_action(meters), distance_action(meters, 'FORWARD_R'),
                           distance_action(meters, 'FORWARD_L'), distance_plan(meters),
                           distance_plan(meters, 'left_then_forward'),
                           distance_plan(meters, 'forward_until_concern'), distance_update(meters)):
                with self.subTest(result=result):
                    self.assertIs(validate_intent(result, 8000), result)

    def test_invalid_distances_and_mode_combinations_are_rejected(self):
        invalid = [distance_action(x) for x in (None, True, False, '5', 0, .049, 100.01,
                    float('inf'), float('nan'), -1, 10**1000)]
        invalid.extend(distance_action(1, a) for a in ('STOP', 'TURN_R', 'TURN_L'))
        invalid.extend(distance_plan(1, p) for p in ('nudge_left', 'nudge_right'))
        invalid.extend((dict(distance_action(), validForMs=4000),
                        dict(distance_action(), executionMode='timed', validForMs=4000),
                        dict(distance_action(), executionMode='until_next_command'),
                        dict(distance_update(), operation='modify_conditions'),
                        dict(distance_update(), executionMode='inherit'),
                        dict(distance_action(), kind='question', action=None),
                        dict(distance_action(), kind='clarify', action=None)))
        for result in invalid:
            with self.subTest(result=str(result)[:200]), self.assertRaises(ControlError):
                validate_intent(result, 8000)

    def test_old_five_and_eight_keys_and_new_null_distance_remain_compatible(self):
        old = {'kind': 'action', 'action': 'FORWARD', 'plan': None, 'validForMs': 4000, 'reply': ''}
        for result in (old, helpers.action(), dict(helpers.action(), distanceMeters=None),
                       dict(helpers.update(), distanceMeters=None)):
            self.assertIs(validate_intent(result, 8000), result)
        missing_extension = dict(old, distanceMeters=1)
        with self.assertRaises(ControlError):
            validate_intent(missing_extension, 8000)

    def test_distance_authority_is_gpt_only_and_has_no_time_deadline(self):
        arbiter = ControlArbiter({'owner': 'gpt', 'maxActionMs': 8000})
        arbiter.resume()
        arbiter.accept('gpt', 'FORWARD', 'distance', arbiter.epoch, None, execution_mode='distance')
        self.assertIsNone(arbiter.deadline)
        for action, duration in (('STOP', None), ('FORWARD', 1000)):
            with self.assertRaises(ControlError):
                arbiter.accept('gpt', action, 'invalid', arbiter.epoch, duration, execution_mode='distance')
        arbiter.owner = 'manual'
        with self.assertRaises(ControlError):
            arbiter.accept('manual', 'FORWARD', 'manual', arbiter.epoch, None, execution_mode='distance')


class DistanceExecutionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = helpers.PersistentExecutionTests.asyncSetUp
    asyncTearDown = helpers.PersistentExecutionTests.asyncTearDown
    propose = helpers.PersistentExecutionTests.propose
    rejected = helpers.PersistentExecutionTests.rejected

    def observation(self, **changes):
        changes.setdefault('travelMeters', 10.0)
        changes.setdefault('horizontalSpeedMetersPerSecond', 0.0)
        return helpers.PersistentExecutionTests.observation(self, **changes)

    async def start(self, meters=5):
        await self.propose(distance_action(meters), 'move-1')
        execution = self.b.active_execution
        self.assertIsNotNone(execution)
        self.b.requests[execution['requestId']]['applied'] = True
        await self.b.check_control_safety()
        return execution

    async def advance(self, seconds, travel, speed=0.0):
        self.now += seconds
        self.observation(travelMeters=travel, horizontalSpeedMetersPerSecond=speed)
        await self.b.check_control_safety()

    async def settle(self, travel=None):
        execution = self.b.active_execution
        self.assertEqual(execution['distancePhase'], 'braking')
        self.b.requests[execution['stopRequestId']]['applied'] = True
        travel = self.b.local_observation.travel_meters if travel is None else travel
        await self.advance(.1, travel)
        await self.advance(.5, travel)

    def finish_result(self, reason):
        results = [call.args[0] for call in self.b.emit.call_args_list
                   if call.args[0].get('stage') == 'execution_finished']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['reason'], reason)
        self.assertEqual(results[0]['completed'], reason == 'distance_reached')
        return results[0]

    async def test_measured_distance_reaches_target_once_and_keeps_voice(self):
        b = self.b
        execution = await self.start()
        epoch, generation = b.arbiter.epoch, b.conversation_generation
        self.assertEqual(execution['originTravelMeters'], 10)
        self.assertIsNone(execution['deadline'])
        self.assertIsNone(b.arbiter.deadline)
        for i in range(1, 5):
            await self.advance(.5, 10 + i)
            self.assertIs(b.current_execution(), execution)
            state = b.execution_state()
            context = b.intent_context()['activeCommand']
            for result in (state, context):
                self.assertEqual(result['targetDistanceMeters'], 5)
                self.assertEqual(result['traveledMeters'], i)
                self.assertEqual(result['remainingMeters'], 5 - i)
        await self.advance(.5, 15)
        self.assertEqual(b.active_execution['distancePhase'], 'braking')
        await self.settle()
        self.assertIsNone(b.active_execution)
        self.assertTrue(b.can_keep_voice_listening())
        self.assertEqual((epoch, generation), (b.arbiter.epoch, b.conversation_generation))
        self.assertEqual([c.args[0] for c in b.adapter.send_action.await_args_list], ['FORWARD', 'STOP'])
        self.assertEqual(self.finish_result('distance_reached')['traveledMeters'], 5)
        await b.check_control_safety()
        self.assertEqual(b.adapter.send_action.await_count, 2)

    async def test_distance_is_not_converted_to_an_eight_second_duration(self):
        execution = await self.start()
        for i in range(1, 21):
            await self.advance(.5, 10 + i * .03)
        self.assertIs(self.b.current_execution(), execution)
        self.assertAlmostEqual(execution['traveledMeters'], .6)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_less_than_two_centimeters_in_eight_seconds_stops_as_incomplete(self):
        await self.start()
        await self.advance(7.9, 10.019)
        self.assertIsNotNone(self.b.active_execution)
        await self.advance(.1, 10.019)
        await self.settle()
        result = self.finish_result('distance_stalled')
        self.assertGreater(result['remainingMeters'], 4.9)
        self.assertTrue(self.b.can_keep_voice_listening())

    async def test_two_centimeter_progress_renews_only_the_stall_clock(self):
        execution = await self.start()
        await self.advance(7.9, 10.02)
        self.assertEqual(execution['lastProgressAt'], self.now)
        await self.advance(7.9, 10.039)
        self.assertIs(self.b.current_execution(), execution)
        await self.advance(.1, 10.039)
        await self.settle()
        self.finish_result('distance_stalled')

    async def test_three_hundred_second_absolute_limit_is_incomplete(self):
        execution = await self.start(100)
        await self.advance(299.9, 11)
        self.assertIs(self.b.current_execution(), execution)
        await self.advance(.1, 11.02)
        await self.settle()
        self.finish_result('distance_timeout')

    async def test_apply_wait_has_its_separate_finite_timeout(self):
        await self.propose(distance_action(), 'move-1')
        await self.advance(8, 10)
        self.assertIsNotNone(self.b.active_execution)
        await self.advance(4, 10)
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.arbiter.reason, 'execution_apply_timeout')

    async def test_no_distance_completion_before_brain_application(self):
        await self.propose(distance_action(.1), 'move-1')
        await self.advance(.2, 10.2)
        self.assertIsNotNone(self.b.active_execution)
        self.b.requests[self.b.active_execution['requestId']]['applied'] = True
        await self.b.check_control_safety()
        await self.settle()
        self.finish_result('distance_reached')

    async def test_distance_admission_requires_fresh_available_odometry(self):
        for changes, reason in (({'travelMeters': -1}, 'distance_observation_unavailable'),):
            self.b.local_observation.clear()
            self.observation(**changes)
            await self.propose(distance_action())
            self.rejected(reason)
            self.assertIsNone(self.b.active_execution)
        self.b.local_observation.clear()
        self.observation()
        self.now += .75
        await self.propose(distance_action())
        self.rejected('local_observation_unavailable')
        self.b.adapter.send_action.assert_not_awaited()

    async def test_missing_observation_and_hazards_revoke_without_claiming_completion(self):
        for change, reason in (({'travelMeters': -1}, 'distance_observation_unavailable'),
                               ({'forwardBlocked': True}, 'forward_blocked'),
                               ({'bodyUnsafe': True}, 'body_unsafe')):
            with self.subTest(reason=reason):
                self.b.local_observation.clear()
                self.observation()
                self.b.arbiter.resume()
                self.b.voice_control_epoch = self.b.arbiter.epoch
                self.counter += 1
                await self.propose(distance_action(), 'case-' + str(self.counter))
                self.b.requests[self.b.active_execution['requestId']]['applied'] = True
                self.observation(**change)
                await self.b.check_control_safety()
                self.assertIsNone(self.b.active_execution)
                self.assertEqual(self.b.arbiter.reason, reason)
        self.assertFalse(any(c.args[0].get('completed') for c in self.b.emit.call_args_list))

    async def test_stale_local_sample_is_not_a_distance_completion(self):
        await self.start()
        self.now += .75
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'local_observation_unavailable')
        self.assertIsNone(self.b.active_execution)

    async def test_regression_or_jump_cannot_hide_between_watchdog_ticks(self):
        for bad, reason in ((9, 'distance_odometry_regressed'), (15, 'distance_odometry_jump')):
            with self.subTest(reason=reason):
                self.b.local_observation.clear()
                self.observation()
                self.b.arbiter.resume()
                self.b.voice_control_epoch = self.b.arbiter.epoch
                self.counter += 1
                await self.propose(distance_action(), 'fault-' + str(self.counter))
                self.b.requests[self.b.active_execution['requestId']]['applied'] = True
                self.now += .1
                self.observation(travelMeters=bad)
                self.observation(travelMeters=bad + .1)
                await self.b.check_control_safety()
                self.assertEqual(self.b.arbiter.reason, reason)
                self.assertIsNone(self.b.active_execution)

    async def test_stop_and_new_operation_discard_the_old_distance(self):
        await self.start()
        await self.propose(helpers.action('STOP', duration=4000), 'stop')
        self.assertIsNone(self.b.active_execution)
        await self.propose(helpers.update(), 'late-update')
        self.rejected('stale_execution')
        await self.propose(distance_action(), 'second-distance')
        await self.propose(helpers.action('TURN_L', duration=2000), 'turn')
        self.assertEqual(self.b.active_execution['executionId'], 'turn')
        self.assertIsNone(self.b.execution_state()['targetDistanceMeters'])
        self.assertEqual(self.b.arbiter.deadline, self.now + 2)

    async def test_explicit_update_restarts_distance_at_current_location_without_resending(self):
        execution = await self.start()
        await self.advance(.5, 11)
        await self.propose(distance_update(2), 'two-more')
        self.assertIs(self.b.active_execution, execution)
        self.assertEqual(execution['originTravelMeters'], 11)
        self.assertEqual(execution['traveledMeters'], 0)
        self.assertEqual(execution['remainingMeters'], 2)
        self.b.adapter.send_action.assert_awaited_once()
        await self.advance(.5, 12)
        await self.advance(.5, 13)
        await self.settle()
        self.finish_result('distance_reached')

    async def test_inherit_and_condition_addition_preserve_origin_progress_and_clocks(self):
        execution = await self.start()
        await self.advance(.5, 11)
        snapshot = copy.deepcopy(execution)
        for operation in ('continue', 'modify_conditions'):
            await self.propose(helpers.update(operation=operation))
            self.assertEqual(self.b.active_execution, snapshot)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_distance_update_rejects_plain_turn_and_nudge(self):
        await self.propose(helpers.action('TURN_R'), 'move-1')
        await self.propose(distance_update(), 'turn-distance')
        self.rejected('invalid_distance_execution')
        self.b.active_execution['plan'] = 'nudge_right'
        await self.propose(distance_update(), 'nudge-distance')
        self.rejected('invalid_distance_execution')
        self.b.adapter.send_action.assert_awaited_once()

    async def test_distance_can_be_changed_to_timed_or_continuous(self):
        await self.start()
        await self.propose(helpers.update(mode='timed', duration=3000))
        self.assertEqual(self.b.arbiter.deadline, self.now + 3)
        self.assertIsNone(self.b.execution_state()['targetDistanceMeters'])
        await self.propose(helpers.update(mode='until_next_command'))
        self.assertIsNone(self.b.arbiter.deadline)
        self.b.adapter.send_action.assert_awaited_once()

    async def test_distance_stop_await_cannot_erase_a_newer_instruction(self):
        execution = await self.start(.1)

        async def send(action, request):
            if action == 'STOP':
                self.assertIs(self.b.active_execution, execution)
                self.assertEqual(execution['distancePhase'], 'braking')
                await self.propose(helpers.action(duration=3000), 'new-command')

        self.b.adapter.send_action.side_effect = send
        await self.advance(.1, 10.1)
        # Decimal subtraction may round just below the target; cross it clearly.
        if self.b.active_execution is execution:
            await self.advance(.1, 10.11)
        self.assertEqual(self.b.active_execution['executionId'], 'new-command')
        self.assertEqual(self.b.arbiter.deadline, self.now + 3)
        self.assertTrue(self.b.can_keep_voice_listening())
        sent = self.b.adapter.send_action.await_count
        await self.b.finish_distance(execution, 'distance_reached')
        self.assertEqual(self.b.adapter.send_action.await_count, sent)

    async def test_stop_transport_failure_is_inhibited(self):
        await self.start(.1)
        self.b.adapter.send_action.side_effect = BrainAdapterError('protocol-only transport failure')
        await self.advance(.1, 10.2)
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.arbiter.reason, 'distance_stop_send_failed')

    async def test_epoch_or_conversation_change_cannot_keep_old_distance(self):
        await self.start()
        self.b.conversation_generation += 1
        await self.b.check_control_safety()
        self.assertIsNone(self.b.active_execution)
        self.assertIsNone(self.b.local_observation.travel_meters)
        self.assertEqual(self.b.local_observation.sequence, 0)
        self.assertEqual(self.b.arbiter.reason, 'execution_context_lost')

    async def test_old_epoch_or_generation_odometry_cannot_replace_current_sample(self):
        event = self.observation()
        for field in ('controlEpoch', 'conversationGeneration'):
            old = dict(event, sequence=event['sequence'] + 1, travelMeters=20)
            old[field] -= 1
            with self.assertRaises(ControlError):
                await self.b.accept_local_observation(old)
            self.assertEqual(self.b.local_observation.travel_meters, 10)

    async def test_local_odometry_optional_field_and_invalid_numeric_values(self):
        event = self.observation()
        old = {k: v for k, v in event.items() if k not in ('travelMeters', 'horizontalSpeedMetersPerSecond')}
        observation = LocalSafetyObservation()
        observation.accept(old)
        self.assertIsNone(observation.summary()['travelMeters'])
        self.assertIsNone(observation.concern())
        for value in (True, '1', -2, float('nan'), float('inf'), 10**1000):
            with self.subTest(value=str(value)[:50]), self.assertRaises(ControlError):
                observation.accept(dict(event, sequence=2, travelMeters=value))
        observation.clear()
        observation.accept(dict(event, sequence=1, travelMeters=0))
        self.assertEqual(observation.require_distance(), 0)

    async def test_distance_is_not_opened_through_direct_command_fields(self):
        with self.assertRaisesRegex(ControlError, 'distance_requires_validated_intent'):
            await self.b.command({'type': 'set_action', 'action': 'FORWARD',
                                  'executionMode': 'distance', 'distanceMeters': 5})
        with self.assertRaisesRegex(ControlError, 'unknown_message'):
            await self.b.command({'type': 'gpt_command', **distance_action()})
        self.b.adapter.send_action.assert_not_awaited()

    async def test_turn_then_forward_runner_counts_only_forward_phase(self):
        b = self.b
        with patch.object(b, 'task', side_effect=lambda coroutine: coroutine.close()):
            await b.plans.begin('right_then_forward', 'move-1', b.arbiter.epoch,
                                b.conversation_generation, None, intent_deadline=self.now + 8,
                                revision=b.intent_revision, execution_mode='distance', distance_meters=.3)
        plan = b.plans.active
        self.assertIsNone(b.active_execution['originTravelMeters'])
        origins = []
        travel = 10.0
        steps = 0

        async def send(action, request):
            b.requests[request]['applied'] = True
            if action == 'FORWARD':
                origins.append(b.active_execution['originTravelMeters'])

        async def tick(_):
            nonlocal travel, steps
            steps += 1
            self.assertLess(steps, 40)
            self.now += .1
            travel += .1
            self.observation(travelMeters=travel)
            await b.check_control_safety()

        b.adapter.send_action.side_effect = send
        with patch('Runtime.Bridge.action_plans.asyncio.sleep', side_effect=tick):
            await b.plans.run(plan, b.arbiter.epoch, b.conversation_generation)
        await self.settle()
        self.assertEqual([c.args[0] for c in b.adapter.send_action.await_args_list], ['TURN_R', 'FORWARD', 'STOP'])
        self.assertEqual(len(origins), 1)
        self.assertGreater(origins[0], 10.3)
        result = self.finish_result('distance_reached')
        self.assertGreaterEqual(result['traveledMeters'], .3)
        self.assertLess(result['traveledMeters'], .41)
        self.assertIsNone(b.plans.active)
        self.assertTrue(b.can_keep_voice_listening())

    async def test_distance_plan_update_keeps_phase_and_application_times(self):
        b = self.b
        with patch.object(b, 'task', side_effect=lambda coroutine: coroutine.close()):
            await b.plans.begin('right_then_forward', 'move-1', b.arbiter.epoch,
                                b.conversation_generation, None, intent_deadline=self.now + 8,
                                revision=b.intent_revision, execution_mode='distance', distance_meters=5)
        plan = b.plans.active
        plan.update(step=1, phaseSent=True, appliedAt=self.now, submittedAt=self.now, applyDeadline=self.now + 12)
        b.update_execution_step('move-1', 'FORWARD', 1)
        request = await b.submit('FORWARD', 'gpt', 'step')
        plan['requestId'] = request
        b.requests[request]['applied'] = True
        await b.check_control_safety()
        await self.advance(.5, 11)
        before = copy.deepcopy(plan)
        await self.propose(distance_update(2))
        self.assertEqual(plan, before)
        self.assertEqual(b.active_execution['originTravelMeters'], 11)
        b.adapter.send_action.assert_awaited_once()

    async def braking(self, meters=5, travel=14, speed=1):
        execution = await self.start(meters)
        await self.advance(1, travel, speed)
        self.assertIs(self.b.active_execution, execution)
        self.assertEqual(execution['distancePhase'], 'braking')
        self.assertFalse(any(c.args[0].get('stage') == 'execution_finished' for c in self.b.emit.call_args_list))
        return execution

    async def test_predictive_stop_keeps_observing_coast_then_reports_actual_distance(self):
        execution = await self.braking()
        self.assertEqual(execution['traveledMeters'], 4)
        self.assertEqual(execution['stopTrigger'], 'distance_approaching')
        self.assertEqual(execution['requestId'], 1)
        self.assertEqual(execution['stopRequestId'], 2)
        self.assertEqual(self.b.intent_context()['activeCommand']['distancePhase'], 'braking')
        self.assertFalse(self.b.intent_context()['activeCommand']['stopApplied'])
        await self.advance(.3, 14.5, .8)
        self.assertEqual(execution['traveledMeters'], 4.5)
        self.assertIs(self.b.active_execution, execution)
        await self.settle(15.1)
        result = self.finish_result('distance_reached')
        self.assertAlmostEqual(result['traveledMeters'], 5.1)
        self.assertTrue(self.b.can_keep_voice_listening())
        self.assertEqual([c.args[0] for c in self.b.adapter.send_action.await_args_list], ['FORWARD', 'STOP'])

    async def test_early_stop_does_not_label_a_shortfall_as_reached(self):
        await self.braking()
        await self.settle(14.1)
        result = self.finish_result('distance_shortfall')
        self.assertAlmostEqual(result['remainingMeters'], .9)
        self.assertTrue(self.b.can_keep_voice_listening())

    async def test_coasting_past_tolerance_is_overshoot_not_reached(self):
        await self.braking(.5, 10.2)
        await self.settle(11.4)
        result = self.finish_result('distance_overshoot')
        self.assertAlmostEqual(result['traveledMeters'], 1.4)
        self.assertTrue(self.b.can_keep_voice_listening())

    async def test_within_tolerance_can_finish_below_target_after_real_travel(self):
        await self.braking(.5, 10.2)
        await self.settle(10.48)
        self.finish_result('distance_reached')

    async def test_zero_travel_never_completes_a_small_target_despite_tolerance(self):
        await self.braking(.05, 10)
        await self.settle(10)
        result = self.finish_result('distance_shortfall')
        self.assertEqual(result['traveledMeters'], 0)

    async def test_braking_requires_fresh_stop_application_before_settling(self):
        execution = await self.braking()
        await self.advance(.1, 15)
        await self.advance(.5, 15)
        self.assertIs(self.b.active_execution, execution)
        self.assertIsNone(execution['settledSince'])
        await self.settle(15)
        self.finish_result('distance_reached')

    async def test_stop_not_applied_in_ten_seconds_is_inhibited(self):
        await self.braking()
        await self.advance(10, 15, 0)
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.arbiter.reason, 'distance_stop_apply_timeout')

    async def test_rejected_stop_is_inhibited(self):
        execution = await self.braking()
        self.b.requests[execution['stopRequestId']]['rejected'] = True
        await self.b.check_control_safety()
        self.assertEqual(self.b.arbiter.reason, 'distance_stop_not_applied')

    async def test_applied_stop_still_moving_at_ten_seconds_finishes_incomplete(self):
        execution = await self.braking()
        self.b.requests[execution['stopRequestId']]['applied'] = True
        await self.advance(10, 15, .04)
        self.finish_result('distance_stop_unsettled')
        self.assertTrue(self.b.can_keep_voice_listening())

    async def test_unchanged_old_snapshot_cannot_prove_half_second_of_stability(self):
        execution = await self.braking()
        self.b.requests[execution['stopRequestId']]['applied'] = True
        await self.advance(.1, 15)
        self.now += .6
        await self.b.check_control_safety()
        self.assertIs(self.b.active_execution, execution)
        self.observation(travelMeters=15)
        await self.b.check_control_safety()
        self.finish_result('distance_reached')

    async def test_one_centimeter_coast_or_speed_resets_stability_window(self):
        execution = await self.braking()
        self.b.requests[execution['stopRequestId']]['applied'] = True
        await self.advance(.1, 15)
        await self.advance(.4, 15.011, .01)
        await self.advance(.4, 15.011, .04)
        self.assertIsNone(execution['settledSince'])
        await self.advance(.1, 15.011)
        await self.advance(.4, 15.011)
        self.assertIs(self.b.active_execution, execution)
        await self.advance(.11, 15.011)
        self.finish_result('distance_reached')

    async def test_speed_missing_rejects_distance_but_old_timed_input_still_works(self):
        self.observation(horizontalSpeedMetersPerSecond=-1)
        await self.propose(distance_action())
        self.rejected('distance_speed_unavailable')
        self.b.adapter.send_action.assert_not_awaited()
        await self.propose(helpers.action(duration=4000), 'timed')
        self.assertEqual(self.b.active_execution['executionId'], 'timed')
        self.b.adapter.send_action.assert_awaited_once()

    async def test_speed_loss_during_braking_is_not_stationary_success(self):
        await self.braking()
        await self.advance(.1, 14, -1)
        self.assertIsNone(self.b.active_execution)
        self.assertEqual(self.b.arbiter.reason, 'distance_speed_unavailable')

    async def test_invalid_or_unknown_speed_cannot_be_a_distance_observation(self):
        event = self.observation()
        for speed in (True, '0', float('nan'), float('inf'), -2, 10**1000):
            with self.subTest(speed=str(speed)[:50]), self.assertRaises(ControlError):
                LocalSafetyObservation().accept(dict(event, horizontalSpeedMetersPerSecond=speed))
        observation = LocalSafetyObservation()
        observation.accept({k: v for k, v in event.items() if k != 'horizontalSpeedMetersPerSecond'})
        self.assertIsNone(observation.concern())
        with self.assertRaisesRegex(ControlError, 'distance_speed_unavailable'):
            observation.require_distance()

    async def restart_in_stop_await(self, proposal, fail_old_stop=False):
        execution = await self.start()
        old_epoch = self.b.arbiter.epoch

        async def send(action, request):
            if action == 'STOP':
                self.assertIs(self.b.active_execution, execution)
                await self.propose(proposal, 'restart-update')
                self.assertIsNot(self.b.active_execution, execution)
                if fail_old_stop:
                    raise BrainAdapterError('old STOP await failed after the new update')

        self.b.adapter.send_action.side_effect = send
        await self.advance(1, 14, 1)
        restarted = self.b.active_execution
        self.assertEqual(restarted['executionId'], execution['executionId'])
        self.assertIsNot(restarted, execution)
        self.assertEqual([c.args[0] for c in self.b.adapter.send_action.await_args_list], ['FORWARD', 'STOP', 'FORWARD'])
        self.assertEqual(self.b.arbiter.epoch, old_epoch)
        self.assertTrue(self.b.can_keep_voice_listening())
        await self.b.finish_distance(execution, 'distance_reached')
        self.assertIs(self.b.active_execution, restarted)
        return restarted

    async def test_distance_update_during_stop_await_restarts_once_with_new_origin(self):
        execution = await self.restart_in_stop_await(distance_update(2))
        self.assertEqual(execution['originTravelMeters'], 14)
        self.assertEqual(execution['distancePhase'], 'moving')
        self.assertEqual(execution['remainingMeters'], 2)
        self.assertEqual(execution['requestId'], 3)
        self.assertIsNone(execution['stopRequestId'])

    async def test_timed_update_during_stop_await_restarts_once(self):
        execution = await self.restart_in_stop_await(helpers.update(mode='timed', duration=3000))
        self.assertEqual(execution['executionMode'], 'timed')
        self.assertEqual(execution['deadline'], self.now + 3)
        self.assertIsNone(execution['distancePhase'])

    async def test_continuous_update_during_stop_await_restarts_once(self):
        execution = await self.restart_in_stop_await(helpers.update(mode='until_next_command'))
        self.assertEqual(execution['executionMode'], 'until_next_command')
        self.assertIsNone(execution['deadline'])

    async def test_late_old_stop_failure_cannot_inhibit_the_restarted_same_id(self):
        await self.restart_in_stop_await(distance_update(2), fail_old_stop=True)

    async def test_inherit_or_added_condition_during_stop_await_preserves_braking(self):
        execution = await self.start()

        async def send(action, request):
            if action == 'STOP':
                before = copy.deepcopy(execution)
                await self.propose(helpers.update(), 'inherit')
                await self.propose(helpers.update(operation='modify_conditions'), 'conditions')
                self.assertIs(self.b.active_execution, execution)
                self.assertEqual(execution, before)

        self.b.adapter.send_action.side_effect = send
        await self.advance(1, 14, 1)
        self.assertEqual(execution['distancePhase'], 'braking')
        self.assertEqual(self.b.adapter.send_action.await_count, 2)
        await self.settle(15)
        self.finish_result('distance_reached')

    async def test_explicit_stop_during_braking_revokes_the_observation_record(self):
        execution = await self.braking()
        await self.propose(helpers.action('STOP', duration=4000), 'explicit-stop')
        self.assertIsNone(self.b.active_execution)
        await self.b.finish_distance(execution, 'distance_reached')
        self.assertFalse(any(c.args[0].get('stage') == 'execution_finished' for c in self.b.emit.call_args_list))
        self.assertTrue(self.b.can_keep_voice_listening())

    async def test_preserve_execution_requires_current_exact_braking_object_and_stop(self):
        execution = await self.braking()
        for action, preserved in (('STOP', dict(execution)), ('FORWARD', execution)):
            with self.assertRaisesRegex(ControlError, 'stale_execution'):
                await self.b.submit(action, 'safety', 'invalid-preserve', preserve_execution=preserved)
        self.assertEqual(self.b.adapter.send_action.await_count, 2)


if __name__ == '__main__':
    unittest.main()
