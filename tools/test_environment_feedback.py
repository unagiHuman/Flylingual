"""Environment contract fixtures only; no external API, Brain, Unity or server."""
import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.environment_feedback import EnvironmentFeedback, SOURCES
from Runtime.Bridge.server import Bridge


def event(kind='run_started', sequence=1, **changes):
    value = dict(type='environment_event', kind=kind, sourceId=sorted(SOURCES[kind])[0],
                 runId='run-1', attempt=1, sequence=sequence, ageMs=0, controlEpoch=1,
                 conversationGeneration=1, brainSequence=10, brainSessionId='session', brainInstanceId='instance')
    value.update(changes)
    return value


class EnvironmentContractTests(unittest.TestCase):
    def started(self):
        feedback = EnvironmentFeedback(400)
        self.assertIsNone(feedback.accept(event(), 1000))
        return feedback

    def test_contacts_once_per_source_and_observations_are_not_neural_inputs(self):
        feedback = self.started()
        for n, source in enumerate(('planning_juice', 'connection_juice'), 2):
            original = event('sugar_contact', n, sourceId=source)
            before = copy.deepcopy(original)
            result = feedback.accept(original, 1000)
            self.assertEqual(original, before)
            self.assertFalse(result['neuralInputApplied'])
            self.assertEqual(result['affectiveProxy'], {'status': 'not_configured', 'rewardAssociated': None,
                                                       'aversiveAssociated': None, 'subjectiveEmotionKnown': False})
        for n, source in enumerate(('planning_juice', 'connection_juice'), 4):
            self.assertIsNone(feedback.accept(event('sugar_contact', n, sourceId=source), 1000))
        for language in ('ja', 'en'):
            text = feedback.summary(1000, language)
            self.assertLessEqual(len(text), 380)
            self.assertIn('未定義' if language == 'ja' else 'not configured', text)

    def test_threat_end_cancel_and_terminal_transitions(self):
        for ending in ('threat_ended', 'threat_cancelled', 'fall', 'swatted'):
            feedback = self.started()
            self.assertIsNone(feedback.accept(event('threat_ended', 2), 1000))
            self.assertTrue(feedback.accept(event('threat_started', 3), 1000)['threatActive'])
            self.assertIsNone(feedback.accept(event('threat_started', 4), 1000))
            result = feedback.accept(event(ending, 5), 1000)
            self.assertIsNotNone(result)
            self.assertIs(result['threatActive'], False if ending == 'threat_ended' else None)
            if ending in ('fall', 'swatted'):
                self.assertIsNone(feedback.accept(event('sugar_contact', 6), 1000))
                self.assertIsNone(feedback.accept(event('threat_started', 7), 1000))

    def test_delivery_snapshot_counts_queue_time_and_cannot_revive_cleared_events(self):
        feedback = self.started()
        feedback.accept(event('sugar_contact', 2, ageMs=300), 1000)
        self.assertEqual(feedback.snapshot(1050)['ageMs'], 350)
        self.assertTrue(feedback.snapshot(1100)['fresh'])
        self.assertFalse(feedback.snapshot(1150)['fresh'])
        self.assertFalse(feedback.snapshot(999)['fresh'])
        feedback.clear_current()
        self.assertIsNone(feedback.snapshot(1100))

    def test_sequence_run_registration_clear_reset_and_expiry(self):
        feedback = EnvironmentFeedback(400)
        with self.assertRaises(ControlError):
            feedback.accept(event('sugar_contact', 2), 1000)
        feedback.accept(event(), 1000)
        feedback.accept(event('sugar_contact', 2, ageMs=100), 1000)
        self.assertIsNotNone(feedback.summary(1300, 'en'))
        self.assertIsNone(feedback.summary(1301, 'en'))
        self.assertIsNone(feedback.summary(999, 'en'))
        for bad in (event('sugar_contact', 2), event('sugar_contact', 3, runId='old'),
                    event('run_started', 3, runId='new')):
            with self.assertRaises(ControlError):
                feedback.accept(bad, 1000)
        feedback.clear_current()
        self.assertIsNone(feedback.summary(1000, 'en'))
        self.assertIsNone(feedback.accept(event('sugar_contact', 3), 1000))  # Consumption survives a temporary clear.
        feedback.accept(event('run_started', 1, runId='run-2', attempt=2), 1000)
        self.assertIsNotNone(feedback.accept(event('sugar_contact', 2, runId='run-2', attempt=2), 1000))
        feedback.reset()
        feedback.accept(event(), 1000)
        self.assertIsNotNone(feedback.accept(event('sugar_contact', 2), 1000))

    def test_invalid_source_and_numeric_values_are_rejected(self):
        for change in ({'kind': 'invented'}, {'sourceId': 'invented'}, {'runId': '../x'},
                       {'attempt': True}, {'attempt': 0}, {'sequence': True}, {'sequence': 0},
                       {'ageMs': True}, {'ageMs': float('nan')}, {'ageMs': float('inf')}, {'ageMs': -1}, {'ageMs': 401}):
            with self.subTest(change=change), self.assertRaises(ControlError):
                self.started().accept({**event('sugar_contact', 2), **change}, 1000)


class BridgeEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = Bridge(copy.deepcopy(_DEFAULT))
        b = self.bridge
        b.control_ws = object()
        b.control_queue = asyncio.Queue(maxsize=128)
        b.conversation_accepting = True
        b.conversation_interaction = 'control'
        b.conversation.state = 'live'
        b.conversation_generation = b.arbiter.epoch = 1
        b.arbiter.inhibited = False
        b.adapter = SimpleNamespace(connected=True, status={'sessionId': 'session', 'instanceId': 'instance'}, send_action=AsyncMock())
        b.frame = {'sequence': 10}
        b.summary = Mock(return_value={'stale': False})
        b.require_fresh = Mock()
        b.log = Mock()
        b.conversation.append = AsyncMock()
        b.accept_environment_event(event())

    async def asyncTearDown(self):
        tasks = tuple(self.bridge.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_admission_rejects_bad_fields_epoch_identity_and_numbers(self):
        for change in ({'extra': 1}, {'controlEpoch': True}, {'controlEpoch': 2},
                       {'conversationGeneration': 2}, {'conversationGeneration': True},
                       {'brainSequence': True}, {'brainSequence': 11}, {'brainSequence': -1},
                       {'brainSessionId': 'old'}, {'brainInstanceId': 'old'}, {'sourceId': 'invented'}, {'ageMs': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ControlError):
                self.bridge.accept_environment_event(event('sugar_contact', 2, **change))
        self.bridge.adapter.send_action.assert_not_awaited()

    async def test_queue_overload_is_dropped_without_motor_calls(self):
        b = self.bridge
        for _ in range(96):
            b.control_queue.put_nowait({'type': 'control'})
        b.accept_environment_event(event('sugar_contact', 2))
        self.assertEqual(b.control_queue.qsize(), 96)
        await b.environment_sender
        b.adapter.send_action.assert_not_awaited()
        self.assertEqual(b.conversation.append.await_args.args[0], 'commentary')
        self.assertLessEqual(len(b.conversation.append.await_args.args[1]), 380)

    async def test_sender_channels_and_expiry_epoch_generation_suppression(self):
        b = self.bridge
        for sequence, kind in enumerate(('sugar_contact', 'threat_started', 'threat_ended', 'fall'), 2):
            b.accept_environment_event(event(kind, sequence))
            await b.environment_sender
            self.assertEqual(b.conversation.append.await_args.args[0], 'commentary' if kind == 'sugar_contact' else 'thinking')
        latest = copy.deepcopy(b.environment.latest)
        for field in ('controlEpoch', 'conversationGeneration'):
            b.conversation.append.reset_mock()
            await b.send_environment_context({**latest, field: 99})
            b.conversation.append.assert_not_awaited()
        b.conversation.append.reset_mock()
        with patch('Runtime.Bridge.server.time.monotonic', return_value=(b.environment.received + 1000) / 1000):
            await b.send_environment_context(latest)
        b.conversation.append.assert_not_awaited()
        b.adapter.send_action.assert_not_awaited()

    async def test_chat_only_and_stale_admission_are_rejected(self):
        b = self.bridge
        b.conversation_interaction = 'chat_only'
        with self.assertRaises(ControlError):
            b.accept_environment_event(event('sugar_contact', 2))

        b.conversation_interaction = 'control'
        b.require_fresh.side_effect = ControlError('fresh_brain_required')
        with self.assertRaisesRegex(ControlError, 'fresh_brain_required'):
            b.accept_environment_event(event('sugar_contact', 2))

    async def test_sender_rechecks_current_safety_identity_and_latest_observation(self):
        b = self.bridge
        b.accept_environment_event(event('sugar_contact', 2))
        await b.environment_sender
        observation = copy.deepcopy(b.environment.latest)
        for target, field, value in ((b.arbiter, 'inhibited', True), (b, 'conversation_interaction', 'chat_only'),
                                     (b.conversation, 'state', 'off'), (b.adapter, 'connected', False),
                                     (b, 'switching', True), (b, 'release_unknown', True),
                                     (b.adapter, 'status', {'sessionId': 'other', 'instanceId': 'instance'}),
                                     (b, 'summary', Mock(return_value={'stale': True}))):
            with self.subTest(field=field), patch.object(target, field, value):
                b.conversation.append.reset_mock()
                await b.send_environment_context(observation)
                b.conversation.append.assert_not_awaited()
        b.environment.clear_current()
        b.conversation.append.reset_mock()
        await b.send_environment_context(observation)
        b.conversation.append.assert_not_awaited()

    async def test_full_small_queue_is_safe_and_new_generation_requires_registration(self):
        b = self.bridge
        b.control_queue = asyncio.Queue(maxsize=1)
        b.control_queue.put_nowait({'type': 'important_control'})
        b.accept_environment_event(event('sugar_contact', 2))
        await b.environment_sender
        self.assertEqual(b.control_queue.qsize(), 1)
        b.conversation_generation = 2
        with self.assertRaises(ControlError):
            b.accept_environment_event(event('sugar_contact', 3, conversationGeneration=2))
        b.accept_environment_event(event('run_started', 1, conversationGeneration=2))
        b.accept_environment_event(event('sugar_contact', 2, conversationGeneration=2))
        await b.environment_sender
        self.assertEqual(b.environment.latest['conversationGeneration'], 2)
        b.adapter.send_action.assert_not_awaited()



if __name__ == '__main__':
    unittest.main()
