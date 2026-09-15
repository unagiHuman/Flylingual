import unittest
import copy
import time
from unittest.mock import AsyncMock, Mock
from Runtime.Bridge.config import _DEFAULT

from Runtime.Bridge.local_visual_observation import LocalVisualObservation
from Runtime.Bridge.control import ControlError
from Runtime.Bridge.server import Bridge


def event(sequence=1, age=0):
    directions = []
    names = ('front', 'front-right', 'right', 'back-right', 'back', 'back-left', 'left', 'front-left')
    for name in names:
        directions.append({'direction': name, 'surface': 'unknown', 'distance': -1,
                           'edge': 'unknown', 'edgeDistance': -1, 'trend': 'unknown',
                           'alignment': 'unknown', 'slope': 'level'})
    return {'type': 'local_visual_observation', 'controlEpoch': 2,
            'conversationGeneration': 4, 'sequence': sequence, 'ageMs': age,
            'facts': {'ground': 'desk', 'moving': False, 'stable': True,
                      'revisited': False, 'directions': directions}}


class LocalVisualObservationTests(unittest.TestCase):
    def test_english_non_bridge_descriptions_and_announcements(self):
        for kind in ('discovery', 'memory', 'hazard'):
            observation = LocalVisualObservation()
            sample = event()
            sample['facts']['revisited'] = kind == 'memory'
            sample['facts']['directions'][0].update(surface='book', distance=.5,
                edge='near' if kind == 'hazard' else 'clear', edgeDistance=.3,
                trend='closer', alignment='left', slope='up')
            observation.accept(sample, now=100)
            description = observation.describe('front', 'en', now=100)
            self.assertIn('book', description)
            self.assertIn('uphill', description)
            self.assertTrue(description.isascii())
            announcement = observation.announcement(now=100, language='en')
            self.assertEqual(announcement['kind'], kind)
            self.assertTrue(announcement['facts']['text'].isascii())
            self.assertNotIn("I'm steady", announcement['facts']['text'])
            self.assertTrue(observation.describe('all', 'en', now=100).isascii())
            self.assertTrue(observation.describe('back', 'en', now=100).isascii())

    def test_accept_and_expiry(self):
        observation = LocalVisualObservation()
        observation.accept(event(), now=100)
        self.assertTrue(observation.summary(now=100.7)['fresh'])
        self.assertFalse(observation.summary(now=100.75)['fresh'])

    def test_reject_duplicate_direction_and_nan(self):
        observation = LocalVisualObservation()
        bad = event()
        bad['facts']['directions'][1]['direction'] = 'front'
        with self.assertRaises(ControlError):
            observation.accept(bad, now=100)
        bad = event()
        bad['facts']['directions'][0]['distance'] = float('nan')
        with self.assertRaises(ControlError):
            observation.accept(bad, now=100)

    def test_stale_sequence_rejected(self):
        observation = LocalVisualObservation()
        observation.accept(event(3), now=100)
        with self.assertRaises(ControlError):
            observation.accept(event(3), now=101)

    def test_unknown_only_has_no_announcement(self):
        observation = LocalVisualObservation()
        sample = event()
        sample['facts']['ground'] = 'unknown'
        observation.accept(sample, now=100)
        self.assertIsNone(observation.announcement(now=100))

    def test_slope_and_compact_description(self):
        observation = LocalVisualObservation()
        sample = event()
        sample['facts']['ground'] = 'unknown'
        sample['facts']['directions'][0].update(surface='ruler', distance=1.2, edge='near', edgeDistance=.4,
                                                trend='closer', alignment='center', slope='up')
        observation.accept(sample, now=100)
        text = observation.describe('front', 'ja', now=100)
        self.assertIn('定規', text)
        self.assertLessEqual(len(text), 250)
        self.assertIn('上り坂', text)

    def test_unknown_is_not_safe(self):
        observation = LocalVisualObservation()
        observation.accept(event(), now=100)
        self.assertNotIn('stale', observation.describe('right', 'ja', now=100))
        self.assertIn('未確認', observation.describe('right', 'ja', now=100))
        self.assertNotIn('安全', observation.describe('right', 'ja', now=100))

    def test_discovery_precedes_ordinary_floor_and_direction_isolated(self):
        observation = LocalVisualObservation()
        sample = event()
        for s in sample['facts']['directions']: s.update(surface='desk', distance=.5, edge='clear')
        sample['facts']['directions'][6].update(surface='ruler', distance=2.1, alignment='left')
        observation.accept(sample, now=100)
        self.assertIn('定規', observation.describe('all', now=100))
        self.assertNotIn('定規', observation.describe('right', now=100))
        self.assertIn('少し左', observation.describe('left', now=100))

    def test_announcement_dedup_and_new_hazard(self):
        observation = LocalVisualObservation()
        observation.accept(event(), now=100)
        self.assertIsNotNone(observation.announcement(now=100))
        observation.accept(event(2), now=105)
        self.assertIsNone(observation.announcement(now=105))
        hazard = event(3)
        hazard['facts']['directions'][2].update(edge='very_near', edgeDistance=.8)
        observation.accept(hazard, now=106)
        self.assertEqual(observation.announcement(now=106)['kind'], 'hazard')

    def test_motion_and_settlement_only_update_question_facts(self):
        observation = LocalVisualObservation()
        moving = event()
        moving['facts'].update(moving=True, stable=False)
        observation.accept(moving, now=100)
        first = observation.announcement(now=100)
        self.assertNotIn('身体', first['facts']['text'])
        observation.accept(event(2), now=105)
        self.assertIsNone(observation.announcement(now=105))
        self.assertEqual(observation.sequence, 2)
        self.assertTrue(observation.summary(now=105)['facts']['stable'])
        self.assertIn('身体は安定', observation.describe(now=105))
        hazard = event(3)
        hazard['facts']['directions'][0].update(edge='very_near', edgeDistance=.2)
        observation.accept(hazard, now=106)
        self.assertEqual(observation.announcement(now=106)['kind'], 'hazard')

    def test_bridge_guidance_precedes_near_edges_and_deduplicates(self):
        observation = LocalVisualObservation()
        sample = event()
        sample['facts']['directions'][1].update(surface='ruler', distance=2, alignment='right')
        sample['facts']['directions'][6].update(edge='near', edgeDistance=2)
        observation.accept(sample, now=100)
        announcement=observation.announcement(now=100)
        self.assertEqual(announcement['kind'], 'discovery')
        self.assertIn('橋', announcement['facts']['text'])
        self.assertIn('少し右', announcement['facts']['text'])
        self.assertIn('bridge', observation.describe('all', 'en', now=100))
        sample['sequence']=2; observation.accept(sample, now=105)
        self.assertIsNone(observation.announcement(now=105))
        sample['sequence']=3; sample['facts']['directions'][1]['alignment']='left'
        observation.accept(sample, now=106)
        self.assertIn('少し左', observation.announcement(now=106)['facts']['text'])
        sample['sequence']=4; sample['facts']['directions'][1]['alignment']='right'
        sample['facts']['directions'][6].update(edge='very_near', edgeDistance=.2)
        observation.accept(sample, now=111)
        self.assertEqual(observation.announcement(now=111)['kind'], 'hazard')
        self.assertIsNone(observation.announcement(now=112))

    def test_question_matching_is_exact_and_bilingual(self):
        self.assertEqual(Bridge.local_visual_question_direction('  右は危ない？ '), 'right')
        self.assertEqual(Bridge.local_visual_question_direction('What can you see?'), 'all')
        self.assertIsNone(Bridge.local_visual_question_direction('右へ進んで、危なければ止まって'))


class BridgeAnnouncementPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_edition_receives_english_bridge_guidance_without_actions(self):
        bridge = Bridge(copy.deepcopy(_DEFAULT))
        bridge.control_ws = object()
        bridge.conversation_accepting = True
        bridge.conversation_interaction = 'control'
        bridge.conversation.state = bridge.conversation.mode = 'text'
        bridge.conversation.settings['language'] = 'en'
        bridge.conversation.last_voice_end_at = time.monotonic() - 10
        bridge.arbiter.epoch = 2
        bridge.conversation_generation = 4
        bridge.player_priority_until = 0
        bridge.neural_output_at = -1e15
        bridge.conversation.append = AsyncMock()
        bridge.adapter = AsyncMock()
        bridge.submit = AsyncMock()
        bridge.emit = Mock()
        bridge.log = Mock()
        sample = event()
        sample['facts']['directions'][1].update(surface='ruler', distance=2, alignment='right')
        await bridge.accept_local_visual_observation(sample)
        messages = [c.args[0] for c in bridge.emit.call_args_list if c.args[0]['type'] == 'conversation_text']
        self.assertEqual(len(messages), 1)
        self.assertIn('bridge', messages[0]['text'])
        self.assertIn('Turn slightly right', messages[0]['text'])
        bridge.conversation.append.assert_not_awaited()
        bridge.submit.assert_not_called()
        bridge.adapter.send_action.assert_not_called()

    async def test_busy_player_keeps_bridge_fact_pending_without_actions(self):
        bridge = Bridge(copy.deepcopy(_DEFAULT))
        bridge.control_ws = object()
        bridge.conversation_accepting = True
        bridge.conversation_interaction = 'control'
        bridge.conversation.state = 'live'
        bridge.conversation.last_voice_end_at = time.monotonic() - 10
        bridge.arbiter.epoch = 2
        bridge.conversation_generation = 4
        bridge.player_priority_until = time.monotonic() + 10
        bridge.neural_output_at = -1e15
        bridge.conversation.append = AsyncMock()
        bridge.adapter = AsyncMock()
        bridge.submit = AsyncMock()
        bridge.emit = Mock()
        bridge.log = Mock()
        sample = event()
        sample['facts']['directions'][1].update(surface='ruler', distance=2, alignment='right')
        await bridge.accept_local_visual_observation(sample)
        self.assertEqual(bridge.local_visual.sequence, 1)
        self.assertTrue(bridge.local_visual.summary()['fresh'])
        self.assertEqual(bridge.local_visual.summary()['facts']['directions'][1]['surface'], 'ruler')
        bridge.conversation.append.assert_not_awaited()
        self.assertIsNone(bridge.local_visual.last_bridge_signature)
        bridge.player_priority_until = 0
        sample['sequence'] = 2
        await bridge.accept_local_visual_observation(sample)
        self.assertEqual(bridge.local_visual.sequence, 2)
        bridge.conversation.append.assert_awaited_once()
        self.assertEqual(bridge.conversation.append.await_args.args[0], 'commentary')
        self.assertIn('bridge (ruler)', bridge.conversation.append.await_args.args[1])
        self.assertIn('slightly right', bridge.conversation.append.await_args.args[1])
        sample['sequence'] = 3
        await bridge.accept_local_visual_observation(sample)
        bridge.conversation.append.assert_awaited_once()
        bridge.submit.assert_not_called()
        bridge.adapter.send_action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
