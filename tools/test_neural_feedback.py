"""Presentation/control protocol tests only; no API, Brain or Unity process."""
import asyncio
import copy
import itertools
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.neural_feedback import NeuralFeedbackScheduler, compact_summary
from Runtime.Bridge.server import Bridge
from tools.test_neural_response import IDENTITY, frame


def evidence(request_id=1, sequence=1):
    return {'eventId': 'test-%d' % sequence, 'eventType': 'RESPONSE_PRESENT', 'fresh': True,
            'expiresAt': 100000, 'controlEpoch': 1, 'conversationGeneration': 1,
            'identity': copy.deepcopy(IDENTITY), 'dedupKey': str(sequence),
            'current': {'requestedRequestId': request_id, 'appliedRequestId': request_id,
                        'stimulusApplied': True, 'observedAction': 'TURN_R',
                        'raw': {'forward': .2, 'turn': .3}, 'motor': {'forward': .1, 'turn': .2}},
            'allowedClaims': ['stimulus_applied', 'selected_direction_response'],
            'body': {'fresh': False, 'correlated': False}, 'residualLayer': 'unresolved'}


def take(scheduler, now=1000, **changes):
    options = {'epoch': 1, 'generation': 1, 'request_id': 1, 'session_id': IDENTITY['sessionId'],
               'inhibited': False, 'chat_only': False, 'busy': False}
    options.update(changes)
    return scheduler.take(now, **options)


class SummaryTests(unittest.TestCase):
    def test_all_sentence_combinations_are_complete_and_bounded(self):
        for language, question, body_fresh, layer, sarcasm in itertools.product(
                ('ja', 'en'), (False, True), (False, True),
                ('unresolved', 'decoder', 'both', 'selected_neural_readout'), (False, True)):
            event = evidence()
            event['allowedClaims'] += ['response_changed_observed_only', 'post_stop_' + layer]
            event['residualLayer'] = layer
            event['current']['observedAction'] = 'STOP'
            event['body'] = {'fresh': body_fresh, 'correlated': body_fresh}
            original = copy.deepcopy(event)
            result = compact_summary(event, language, question=question, no_sarcasm=sarcasm)
            self.assertLessEqual(len(result), 380)
            self.assertTrue(result.rstrip().endswith(('.', '。')))
            self.assertIn('原因は未確定' if language == 'ja' else 'Cause unknown', result)
            self.assertIn('未確' if language == 'ja' else 'unverified', result)
            self.assertEqual(event, original)

    def test_personas_do_not_change_claims_or_evidence(self):
        for language in ('ja', 'en'):
            event = evidence()
            expected = compact_summary(event, language)
            for persona in ('hiroyuki_like', 'deadpan_skeptic', 'friendly'):
                decorated = {**event, 'persona': persona}
                self.assertEqual(compact_summary(decorated, language), expected)
                self.assertEqual(decorated['allowedClaims'], event['allowedClaims'])

    def test_unknown_and_inhibited_never_emit_numeric_observation(self):
        for event in (None, {**evidence(), 'fresh': False}, {**evidence(), 'outputInhibited': True}):
            for language in ('ja', 'en'):
                result = compact_summary(event, language, question=True)
                self.assertNotIn('VNC raw', result)
                self.assertIn('不明' if language == 'ja' else 'unavailable', result)


class SchedulerTests(unittest.TestCase):
    def test_pending_replaces_and_question_is_not_rate_limited(self):
        scheduler = NeuralFeedbackScheduler()
        scheduler.offer(evidence(sequence=1))
        scheduler.offer(evidence(sequence=2))
        event, reason = take(scheduler)
        self.assertEqual(event['eventId'], 'test-2')
        self.assertIsNone(reason)
        self.assertIsNone(scheduler.pending)
        scheduler.offer(evidence(sequence=3))
        self.assertEqual(take(scheduler, now=1001)[1], 'cooldown')
        self.assertIn('最新の質問', compact_summary(evidence(), question=True))

    def test_generation_request_session_freshness_and_priority_gates(self):
        for overrides in ({'epoch': 2}, {'generation': 2}, {'request_id': 2}, {'session_id': 'other'},
                          {'inhibited': True}, {'chat_only': True}, {'busy': True}):
            scheduler = NeuralFeedbackScheduler()
            scheduler.offer(evidence())
            self.assertIsNone(take(scheduler, **overrides)[0])
            self.assertIsNone(scheduler.pending)
        for expiry in (-1, float('nan'), float('inf')):
            scheduler = NeuralFeedbackScheduler()
            scheduler.offer({**evidence(), 'expiresAt': expiry})
            self.assertIsNone(take(scheduler)[0])

    def test_preferences_interrupt_and_disabled_do_not_block_questions(self):
        for preference in ('実況を減らして', 'stop commentary'):
            scheduler = NeuralFeedbackScheduler()
            scheduler.offer(evidence())
            scheduler.preference(preference)
            self.assertIsNone(scheduler.pending)
            scheduler.offer(evidence())
            self.assertIsNone(take(scheduler)[0])
            self.assertTrue(compact_summary(evidence(), question=True))
        scheduler = NeuralFeedbackScheduler({'spontaneousEnabled': False})
        scheduler.offer(evidence())
        self.assertIsNone(take(scheduler)[0])
        scheduler.preference('皮肉はやめて')
        self.assertTrue(scheduler.no_sarcasm)
        scheduler.interrupt(1000)
        self.assertIsNone(scheduler.pending)


class BridgeFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_question_reaches_live_and_facts_are_not_forced_commentary(self):
        b = self.bridge
        b.conversation.mode = 'live'
        b.intent_context = Mock(return_value={})
        b.conversation.interpret = AsyncMock(return_value={'kind': 'question', 'action': None,
            'validForMs': 0, 'reply': '', 'plan': None})
        await b.player_intent('宇宙について教えて', 'typed-test', 1, b.intent_revision, None)
        calls = b.conversation.append.await_args_list
        self.assertTrue(any('宇宙について教えて' in call.args[1] for call in calls))
        self.assertEqual(calls[-1].args[0], 'instructions')
        self.assertTrue(all(call.args[0] != 'commentary' for call in calls))
        self.assertTrue(all(len(call.args[1]) <= 380 for call in calls))

    async def test_speech_started_after_scheduling_prevents_spontaneous_send(self):
        b = self.bridge
        b.conversation.last_voice_end_at = time.monotonic()
        await b.send_neural_context('commentary', evidence())
        b.conversation.append.assert_not_awaited()

    async def asyncSetUp(self):
        config = copy.deepcopy(_DEFAULT)
        config['neuralFeedback'] = {**config.get('neuralFeedback', {}), 'enabled': True}
        self.bridge = Bridge(config)
        b = self.bridge
        b.adapter = SimpleNamespace(connected=True, status=copy.deepcopy(IDENTITY), send_action=AsyncMock())
        b.log = Mock()
        b.age_ms = Mock(return_value=0)
        b.conversation.state = 'live'
        b.conversation.append = AsyncMock()
        b.conversation_accepting = True
        b.conversation_generation = 1
        b.arbiter.epoch = 1
        b.arbiter.inhibited = False
        b.request_counter = 1
        b.neural_snapshot = Mock(return_value=evidence())

    async def asyncTearDown(self):
        tasks = tuple(self.bridge.tasks | self.bridge.intent_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_no_chat_only_observation_append_or_question_leak(self):
        b = self.bridge
        b.conversation_interaction = 'chat_only'
        await b.send_neural_context('commentary', evidence())
        b.conversation.append.assert_not_awaited()
        b.intent_context = Mock(side_effect=AssertionError('chat_only must not read Brain observations'))
        self.assertTrue(b.non_action_reply_context('今どう？', 'question'))

    async def test_queued_old_request_or_generation_cannot_append(self):
        b = self.bridge
        old = evidence(request_id=1)
        b.request_counter = 2
        b.neural_snapshot.return_value = evidence(request_id=2)
        await b.send_neural_context('commentary', old)
        b.conversation.append.assert_not_awaited()
        b.request_counter = 1
        b.neural_snapshot.return_value = {**evidence(), 'conversationGeneration': 2}
        await b.send_neural_context('commentary', old)
        b.conversation.append.assert_not_awaited()

    async def test_stop_delivery_does_not_wait_for_commentary(self):
        b = self.bridge
        never_finish = asyncio.Event()
        b.conversation.append.side_effect = lambda *args: never_finish.wait()
        pending = b.task(never_finish.wait())
        b.neural_sender = pending
        b.neural_scheduler.offer(evidence())
        await asyncio.wait_for(b.submit('STOP', 'safety', 'stop-test'), .1)
        b.adapter.send_action.assert_awaited_once_with('STOP', 2)
        self.assertIsNone(b.neural_scheduler.pending)
        self.assertFalse(pending.done())

    async def test_feature_off_emits_no_hud_or_append_tasks(self):
        b = self.bridge
        b.neural.enabled = False
        b.control_queue = asyncio.Queue()
        b.neural_subscribed = True
        b.publish_neural()
        self.assertTrue(b.control_queue.empty())
        self.assertEqual(len(b.tasks), 0)
        b.conversation.append.assert_not_awaited()

    async def test_pending_sender_and_hud_queue_are_bounded(self):
        b = self.bridge
        pending = b.task(asyncio.Event().wait())
        b.neural_sender = pending
        b.control_queue = asyncio.Queue(maxsize=128)
        b.neural_subscribed = True
        for _ in range(95):
            b.control_queue.put_nowait({'type': 'existing_control'})
        for _ in range(30):
            b.publish_neural()
        self.assertEqual(b.control_queue.qsize(), 96)
        self.assertEqual(len(b.tasks), 1)
        self.assertIs(b.neural_sender, pending)

    async def test_clear_discards_pending_body_and_cancels_sender(self):
        b = self.bridge
        pending = b.task(asyncio.Event().wait())
        b.neural_sender = pending
        b.neural_scheduler.offer(evidence())
        b.neural_body = {'old': True}
        b.clear_neural()
        await asyncio.gather(pending, return_exceptions=True)
        self.assertTrue(pending.cancelled())
        self.assertIsNone(b.neural_scheduler.pending)
        self.assertIsNone(b.neural_body)

    async def test_observation_is_non_mutating_and_api_free(self):
        b = self.bridge
        b.requests[1] = {'action': 'TURN_R', 'epoch': 1, 'sent': time.monotonic()}
        source = frame(0, applied=1)
        original = copy.deepcopy(source)
        b.observe_neural(source)
        self.assertEqual(source, original)
        b.conversation.append.assert_not_awaited()
        self.assertEqual(len(b.tasks), 0)

    async def test_body_contract_types_freshness_and_order(self):
        b = self.bridge
        b.neural_subscribed = True
        payload = {'type': 'body_response_observation', 'controlEpoch': 1, 'conversationGeneration': 1,
                   'sequence': 1, 'ageMs': 0, 'brainSequence': 1, 'brainSessionId': IDENTITY['sessionId'],
                   'brainInstanceId': IDENTITY['instanceId'], 'horizontalSpeedMetersPerSecond': .2}
        b.accept_neural_body(payload)
        before = copy.deepcopy(b.neural_body)
        b.accept_neural_body({**payload, 'horizontalSpeedMetersPerSecond': 4})
        self.assertEqual(b.neural_body, before)
        b.accept_neural_body({**payload, 'sequence': 2, 'brainSessionId': 'old'})
        self.assertEqual(b.neural_body, before)
        for change in ({'sequence': True}, {'ageMs': float('nan')}, {'ageMs': 751}, {'unexpected': 1},
                       {'brainSessionId': None}, {'horizontalSpeedMetersPerSecond': -.2}, {'travelMeters': -1}):
            with self.subTest(change=change), self.assertRaises(ControlError):
                b.accept_neural_body({**payload, **change})


if __name__ == '__main__':
    unittest.main()
