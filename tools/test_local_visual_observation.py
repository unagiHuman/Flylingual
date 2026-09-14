import unittest

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

    def test_question_matching_is_exact_and_bilingual(self):
        self.assertEqual(Bridge.local_visual_question_direction('  右は危ない？ '), 'right')
        self.assertEqual(Bridge.local_visual_question_direction('What can you see?'), 'all')
        self.assertIsNone(Bridge.local_visual_question_direction('右へ進んで、危なければ止まって'))


if __name__ == '__main__':
    unittest.main()
