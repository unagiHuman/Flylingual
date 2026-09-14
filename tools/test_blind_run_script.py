"""Pure cue-selector regression checks; no Unity, Brain or API simulation."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Runtime.Bridge.blind_run_script import BlindRunScript
from Runtime.Bridge.control import ControlError

CATALOG = json.loads((Path(__file__).resolve().parents[1] /
                     'Runtime/Bridge/blind_run_script.json').read_text(encoding='utf-8'))['cues']


def cue(name, sequence=1, attempt=1, evidence=None):
    return dict(type='blind_run_cue', controlEpoch=1, conversationGeneration=1,
                runId='test-run', attempt=attempt, sequence=sequence, ageMs=0,
                cue=name, evidence=copy.deepcopy(CATALOG[name]['evidence']) if evidence is None else evidence)


class CueSelectorTests(unittest.TestCase):
    def started(self):
        script = BlindRunScript()
        script.accept(cue('intro'), 'ja', now=10)
        return script

    def test_catalog_languages_and_typed_evidence(self):
        for language in ('ja', 'en'):
            for name, item in CATALOG.items():
                with self.subTest(language=language, cue=name):
                    script = self.started()
                    if name == 'reveal':
                        script.accept(cue('goal', 2), language, now=14)
                    text, _ = script.accept(cue(name, 3), language, now=18)
                    self.assertEqual(text, item[language])
                    invalid = cue(name, 4)
                    key = next(iter(invalid['evidence']))
                    value = invalid['evidence'][key]
                    invalid['evidence'][key] = int(value) if type(value) is bool else 'unobserved'
                    with self.assertRaises(ControlError):
                        script.accept(invalid, language, now=22)

    def test_intro_freshness_order_and_no_extra_map(self):
        with self.assertRaisesRegex(ControlError, 'intro_required'):
            BlindRunScript().accept(cue('book'), 'ja', now=10)
        script = self.started()
        for change in ({'ageMs': 751}, {'ageMs': float('nan')}, {'ageMs': float('inf')},
                       {'sequence': 1}, {'runId': 'old-run'}, {'attempt': 2}, {'map': 'route'}):
            event = cue('book', 2)
            event.update(change)
            with self.subTest(change=change), self.assertRaises(ControlError):
                script.accept(event, 'ja', now=14)
        self.assertEqual(script.sequence, 1)

    def test_rate_limit_and_urgent_exception(self):
        script = self.started()
        self.assertFalse(script.accept(cue('book', 2), 'ja', now=11)[1])
        self.assertTrue(script.accept(cue('right_edge_urgent', 3), 'ja', now=11.1)[1])
        self.assertFalse(script.accept(cue('right_edge_urgent', 4), 'ja', now=15)[1])
        self.assertFalse(script.accept(cue('intro', 5), 'ja', now=19)[1])

    def test_fall_retry_and_reset_do_not_invent_cause(self):
        script = self.started()
        evidence = dict(ground='ruler', lastAction='TURN_R', leftEdge='safe',
                        rightEdge='very_near', technicalFault=False)
        script.accept(cue('fall', 2, evidence=evidence), 'ja', now=14)
        with self.assertRaisesRegex(ControlError, 'retry_required'):
            script.accept(cue('book', 3), 'ja', now=18)
        text, speak = script.accept(cue('retry', 3, 2, {}), 'ja', now=18)
        self.assertEqual(text, '前は、右の端が近かった。')
        self.assertTrue(speak)
        self.assertIsNone(script.last_fall)
        script.reset()
        self.assertIsNone(script.run_id)
        self.assertIsNone(script.current_fact())
        with self.assertRaisesRegex(ControlError, 'intro_required'):
            script.accept(cue('retry', 4, 3, {}), 'ja', now=22)

    def test_fault_is_not_a_fall_and_reveal_requires_goal(self):
        script = self.started()
        with self.assertRaisesRegex(ControlError, 'goal_required'):
            script.accept(cue('reveal', 2), 'ja', now=14)
        script.accept(cue('link_error', 2), 'ja', now=14)
        self.assertFalse(script.fallen)
        with self.assertRaisesRegex(ControlError, 'retry_requires_fall'):
            script.accept(cue('retry', 3, 2, {}), 'ja', now=18)
        script.accept(cue('goal', 3), 'ja', now=18)
        self.assertTrue(script.accept(cue('reveal', 4), 'ja', now=22)[1])

    def test_goal_ack_retry_is_idempotent_and_does_not_reopen_game(self):
        script = self.started()
        self.assertTrue(script.accept(cue('goal', 2), 'ja', now=14)[1])
        self.assertFalse(script.accept(cue('goal', 3), 'ja', now=18)[1])
        with self.assertRaisesRegex(ControlError, 'goal_already_confirmed'):
            script.accept(cue('book', 4), 'ja', now=22)
        self.assertTrue(script.accept(cue('reveal', 4), 'ja', now=22)[1])
        self.assertFalse(script.accept(cue('reveal', 5), 'ja', now=26)[1])

    def test_visible_motion_cues_keep_facts_without_speech(self):
        script = self.started()
        for sequence, name in enumerate(('still_moving', 'stable'), 2):
            text, speak = script.accept(cue(name, sequence), 'ja', now=10 + sequence * 4)
            self.assertFalse(speak)
            self.assertEqual(script.sequence, sequence)
            self.assertEqual(script.last_fact, text)
        self.assertTrue(script.accept(cue('right_edge_urgent', 4), 'ja', now=30)[1])

    def test_bridge_cues_explain_observed_alignment_bilingually(self):
        for language in ('ja', 'en'):
            for name, direction in (('ruler_right', '右' if language=='ja' else 'right'),
                                    ('ruler_left', '左' if language=='ja' else 'left')):
                script=self.started()
                text,speak=script.accept(cue(name,2),language,now=14)
                self.assertTrue(speak)
                self.assertIn('橋' if language=='ja' else 'bridge',text)
                self.assertIn(direction,text)

    def test_swatter_warning_urgent_deduplicated_and_rearmed_by_escape(self):
        script = self.started()
        self.assertTrue(script.accept(cue('swatter_warning', 2), 'ja', now=10.1)[1])
        script.accept(cue('right_edge_urgent', 3), 'ja', now=10.2)
        self.assertFalse(script.accept(cue('swatter_warning', 4), 'ja', now=10.3)[1])
        self.assertFalse(script.accept(cue('swatter_escaped', 5), 'ja', now=10.4)[1])
        self.assertTrue(script.accept(cue('swatter_warning', 6), 'ja', now=10.5)[1])

    def test_swatted_is_death_without_fabricated_fall_memory(self):
        script = self.started()
        text, speak = script.accept(cue('swatted', 2), 'ja', now=10.1)
        self.assertEqual(text, 'ハエたたきに叩かれた。')
        self.assertTrue(speak)
        self.assertTrue(script.fallen)
        self.assertIsNone(script.last_fall)
        with self.assertRaisesRegex(ControlError, 'retry_required'):
            script.accept(cue('swatter_warning', 3), 'ja', now=14)
        text, _ = script.accept(cue('retry', 3, 2, {}), 'ja', now=14)
        self.assertEqual(text, 'もう一回。')
        self.assertTrue(script.accept(cue('swatter_warning', 4, 2), 'ja', now=14.1)[1])

    def test_swatter_evidence_and_existing_run_guards(self):
        for name in ('swatter_warning', 'swatter_escaped', 'swatted'):
            with self.subTest(cue=name):
                with self.assertRaisesRegex(ControlError, 'intro_required'):
                    BlindRunScript().accept(cue(name), 'ja', now=10)
                script = self.started()
                invalid = cue(name, 2)
                invalid['evidence']['route'] = 'global-map'
                with self.assertRaisesRegex(ControlError, 'evidence_mismatch'):
                    script.accept(invalid, 'ja', now=11)
                with self.assertRaisesRegex(ControlError, 'old_blind_run_or_sequence'):
                    script.accept(cue(name, 1), 'ja', now=11)
                script.accept(cue('goal', 2), 'ja', now=14)
                with self.assertRaisesRegex(ControlError, 'goal_already_confirmed'):
                    script.accept(cue(name, 3), 'ja', now=15)


if __name__ == '__main__':
    unittest.main()
