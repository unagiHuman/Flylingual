"""Pure contract/fake transport tests; no Brain, Unity or external API execution."""
import asyncio
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.brain_adapter import BrainAdapter, BrainAdapterError
from Runtime.Bridge.visual_threat_feedback import validate_readout, describe
from Runtime.Bridge.server import Bridge
from Runtime.Bridge.config import _DEFAULT
from tools.test_environment_feedback import event


def raw(active=True, request_id=-1):
    return dict(schemaVersion=1, stimulusModel='event_proxy_v1', active=active,
                inputEventCount=2 if active else 0, requestId=request_id, reason='active' if active else 'wall_timeout',
                readouts={'R': dict(bodyId=10001, spikeCount=2, rateHz=40.0),
                          'L': dict(bodyId=10010, spikeCount=0, rateHz=0.0)})


class ContractTests(unittest.TestCase):
    def test_schema_fixed_ids_counts_and_rate_window(self):
        value = raw()
        self.assertEqual(validate_readout(value, 50), value)
        self.assertIsNone(validate_readout({**value, 'active': False}, 50))
        self.assertEqual(validate_readout(raw(False), 50), raw(False))
        changes = [('schemaVersion', True), ('active', 1), ('inputEventCount', -1),
                   ('inputEventCount', True), ('inputEventCount', 10**1000), ('requestId', 1.0), ('stimulusModel', 'retina'), ('reason', '')]
        for key, invalid in changes:
            self.assertIsNone(validate_readout({**value, key: invalid}, 50))
        self.assertIsNone(validate_readout({**value, 'extra': 1}, 50))
        for key, invalid in [('bodyId', 10010), ('bodyId', True), ('spikeCount', -1),
                             ('spikeCount', 2.0), ('rateHz', float('nan')), ('rateHz', 41)]:
            altered = copy.deepcopy(value)
            altered['readouts']['R'][key] = invalid
            self.assertIsNone(validate_readout(altered, 50))
        for window in (None, True, 0, -1, float('inf'), 100):
            self.assertIsNone(validate_readout(value, window))

    def test_bilingual_bounded_factual_persona_context(self):
        for language in ('ja', 'en'):
            text = describe({'raw': raw()}, language)
            self.assertLessEqual(len(text), 380)
            self.assertIn('40', text)
            self.assertIn('人格' if language == 'ja' else 'persona', text)
            self.assertIn('未確認' if language == 'ja' else 'unverified', text)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = AsyncMock()
        self.a = BrainAdapter(self.messages)
        self.a.connected = True
        self.a.status = {'capabilities': ['visual_threat_v1']}
        self.a._writer = SimpleNamespace(is_closing=lambda: False, write=Mock(), drain=AsyncMock())

    def sent(self):
        return [json.loads(c.args[0]) for c in self.a._writer.write.call_args_list]

    async def test_exact_payload_negative_ids_and_separate_ack(self):
        first = await self.a.send_visual_threat(True, 700, source={'event': 2})
        second = await self.a.send_visual_threat(False, 0, source={'event': 2})
        self.assertLess(second, first)
        self.assertLess(first, 0)
        self.assertEqual(set(self.sent()[0]), {'type', 'requestId', 'active', 'validForMs'})
        await self.a._handle_message(dict(type='visual_threat_ack', requestId=first, accepted=True, active=True), {})
        self.assertEqual(self.messages.await_args.args[0]['source'], {'event': 2})
        self.assertEqual(self.messages.await_args.args[0]['type'], 'visual_threat_ack')
        self.messages.reset_mock()
        await self.a._handle_message(dict(type='visual_threat_ack', requestId=999, accepted=True, active=True), {})
        self.messages.assert_not_awaited()

    async def test_legacy_capability_and_invalid_contract(self):
        self.a.status = {}
        self.assertIsNone(await self.a.send_visual_threat(True, 500, source={}))
        self.assertEqual(self.sent(), [])
        for active, ttl in ((True, 0), (True, 751), (False, 1), (1, 500), (True, True)):
            with self.assertRaises(BrainAdapterError):
                await self.a.send_visual_threat(active, ttl, source={})

    async def test_lock_wait_reduces_ttl_and_expired_start_is_not_sent(self):
        for elapsed, expected in ((.2, 200), (.5, None)):
            self.a._writer.write.reset_mock()
            clock = [10.0]
            with patch('Runtime.Bridge.brain_adapter.time', SimpleNamespace(monotonic=lambda: clock[0])):
                await self.a._write_lock.acquire()
                task = asyncio.create_task(self.a.send_visual_threat(True, 400, source={}))
                await asyncio.sleep(0)
                clock[0] += elapsed
                self.a._write_lock.release()
                result = await task
            if expected is None:
                self.assertIsNone(result)
                self.assertEqual(self.sent(), [])
            else:
                self.assertLessEqual(self.sent()[0]['validForMs'], expected)
                self.assertGreater(self.sent()[0]['validForMs'], 190)

    async def test_stop_invalidates_queued_sensory_before_action_write(self):
        await self.a._write_lock.acquire()
        sensory = asyncio.create_task(self.a.send_visual_threat(True, 700, source={}))
        await asyncio.sleep(0)
        stop = asyncio.create_task(self.a.send_action('STOP', 4))
        await asyncio.sleep(0)
        self.a._write_lock.release()
        await asyncio.gather(sensory, stop)
        self.assertEqual(self.sent(), [dict(type='set_action', action='STOP', requestId=4)])

    async def test_obsolete_off_does_not_invalidate_new_queued_on(self):
        await self.a._write_lock.acquire()
        sensory = asyncio.create_task(self.a.send_visual_threat(True, 700, source={}))
        await asyncio.sleep(0)
        await self.a.send_visual_threat(False, 0, source={}, valid=lambda: False)
        self.a._write_lock.release()
        await sensory
        self.assertEqual(len(self.sent()), 1)
        self.assertTrue(self.sent()[0]['active'])

    async def test_send_time_scope_change_and_sensory_error_are_isolated(self):
        self.assertIsNone(await self.a.send_visual_threat(True, 500, source={}, valid=lambda: False))
        rid = await self.a.send_visual_threat(True, 500, source={})
        await self.a._handle_message(dict(type='error', requestId=rid, error='invalid_visual_threat'), {})
        self.messages.assert_not_awaited()


class IntegrationContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = b = Bridge(copy.deepcopy(_DEFAULT))
        b.control_ws = object()
        b.control_queue = asyncio.Queue(maxsize=128)
        b.conversation_accepting = True
        b.conversation.state = 'text'
        b.conversation_generation = b.arbiter.epoch = 1
        b.arbiter.inhibited = False
        a = BrainAdapter(AsyncMock())
        a.connected = True
        a.status = dict(capabilities=['visual_threat_v1'], windowMs=50, sessionId='session', instanceId='instance')
        a._writer = SimpleNamespace(is_closing=lambda: False, write=Mock(), drain=AsyncMock())
        b.adapter = a
        b.frame = {'sequence': 10}
        b.summary = Mock(return_value={'stale': False})
        b.require_fresh = Mock()
        b.log = Mock()
        b.conversation.append = AsyncMock()
        b.accept_environment_event(event())

    async def asyncTearDown(self):
        tasks = tuple(self.b.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def settle(self):
        for _ in range(8):
            await asyncio.sleep(0)

    def sensory(self):
        return [json.loads(c.args[0]) for c in self.b.adapter._writer.write.call_args_list]

    def frame(self, rid, active=True, sequence=11):
        return dict(type='brain_frame', sequence=sequence, metadata=dict(sessionId='session', instanceId='instance'),
                    raw={'visualThreat': raw(active, rid)}, motor={'forward': .1, 'turn': 0})

    async def test_fresh_warning_once_and_end_off(self):
        b = self.b
        b.accept_environment_event(event('threat_started', 2, ageMs=300))
        await self.settle()
        b.accept_environment_event(event('threat_started', 3))
        await self.settle()
        self.assertEqual(len(self.sensory()), 1)
        self.assertTrue(self.sensory()[0]['active'])
        self.assertLessEqual(self.sensory()[0]['validForMs'], 450)
        b.accept_environment_event(event('threat_ended', 4))
        await self.settle()
        self.assertFalse(self.sensory()[-1]['active'])
        self.assertEqual(self.sensory()[-1]['validForMs'], 0)

    async def test_queued_start_dropped_for_all_scope_changes(self):
        for change in ('clear', 'epoch', 'generation', 'stale', 'inhibit', 'identity', 'cancel'):
            with self.subTest(change=change):
                b = self.b
                b.environment.reset()
                b.accept_environment_event(event())
                b.accept_environment_event(event('threat_started', 2))
                if change == 'clear': b.clear_neural()
                if change == 'epoch': b.arbiter.epoch += 1
                if change == 'generation': b.conversation_generation += 1
                if change == 'stale': b.summary.return_value = {'stale': True}
                if change == 'inhibit': b.arbiter.inhibited = True
                if change == 'identity': b.adapter.status['sessionId'] = 'other'
                if change == 'cancel': b.accept_environment_event(event('threat_cancelled', 3))
                await self.settle()
                self.assertFalse(any(v['active'] for v in self.sensory()))
                b.adapter._writer.write.reset_mock()
                b.arbiter.epoch = b.conversation_generation = 1
                b.summary.return_value = {'stale': False}
                b.arbiter.inhibited = False
                b.adapter.status['sessionId'] = 'session'

    async def test_raw_observation_freshness_identity_and_invalid_rate(self):
        b = self.b
        b.accept_environment_event(event('threat_started', 2))
        await self.settle()
        rid = self.sensory()[0]['requestId']
        b.observe_visual_threat(self.frame(rid))
        self.assertEqual(b.visual_threat_snapshot()['raw'], raw(True, rid))
        self.assertEqual(b.visual_threat_snapshot()['brainSequence'], 11)
        received = b.visual_threat_latest['_receivedMs']
        with patch('Runtime.Bridge.visual_threat_feedback.time.monotonic', return_value=(received+751)/1000):
            self.assertIsNone(b.visual_threat_snapshot())
        wrong = self.frame(rid)
        wrong['raw']['visualThreat']['readouts']['R']['rateHz'] = 41
        b.observe_visual_threat(wrong)
        self.assertIsNone(b.visual_threat_snapshot())
        b.observe_visual_threat(self.frame(rid))
        b.clear_neural()
        self.assertIsNone(b.visual_threat_snapshot())
        b.observe_visual_threat(self.frame(rid))
        self.assertIsNone(b.visual_threat_snapshot())

    async def test_end_off_is_observable_but_clear_off_is_not(self):
        b = self.b
        b.accept_environment_event(event('threat_started', 2))
        await self.settle()
        b.accept_environment_event(event('threat_ended', 3))
        await self.settle()
        off_id = self.sensory()[-1]['requestId']
        b.observe_visual_threat(self.frame(off_id, active=False))
        self.assertFalse(b.visual_threat_snapshot()['raw']['active'])
        b.accept_environment_event(event('threat_started', 4))
        await self.settle()
        b.clear_neural()
        await self.settle()
        clear_id = self.sensory()[-1]['requestId']
        b.observe_visual_threat(self.frame(clear_id, active=False))
        self.assertIsNone(b.visual_threat_snapshot())

    async def test_expired_start_400ms_and_legacy_brain(self):
        b = self.b
        b.config['control']['staleMs'] = 400
        b.accept_environment_event(event('threat_started', 2, ageMs=390))
        b.visual_threat_source['receivedMs'] -= 20
        await self.settle()
        self.assertEqual(self.sensory(), [])
        b.environment.clear_current()
        b.adapter.status['capabilities'] = []
        b.accept_environment_event(event('threat_started', 3))
        await self.settle()
        self.assertEqual(self.sensory(), [])

    async def test_invalid_raw_never_interrupts_existing_motor_frame(self):
        b = self.b
        b.motor_writer = object()
        b.motor_emit = Mock()
        frame = self.frame(-999)
        frame['raw']['visualThreat']['readouts']['R']['rateHz'] = float('nan')
        await b.brain_message(frame)
        b.motor_emit.assert_called_once()
        self.assertEqual(b.motor_emit.call_args.args[0]['motor'], frame['motor'])

    async def test_low_priority_queue_and_context_dedup(self):
        b = self.b
        b.accept_environment_event(event('threat_started', 2))
        await self.settle()
        rid = self.sensory()[0]['requestId']
        b.conversation.append.reset_mock()
        while b.control_queue.qsize() < 96:
            b.control_queue.put_nowait({'type': 'control'})
        b.observe_visual_threat(self.frame(rid))
        await self.settle()
        self.assertEqual(b.control_queue.qsize(), 96)
        self.assertEqual(b.conversation.append.await_count, 1)
        self.assertEqual(b.conversation.append.await_args.args[0], 'thinking')
        b.observe_visual_threat(self.frame(rid, sequence=12))
        await self.settle()
        self.assertEqual(b.conversation.append.await_count, 1)


if __name__ == '__main__':
    unittest.main()
