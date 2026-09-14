"""Pure error-envelope checks: no Brain or Unity substitute."""
import unittest

from Runtime.Bridge.control import ControlError
from Runtime.Bridge.server import command_error_message


class StaleObservationErrors(unittest.TestCase):
    def test_old_observation_has_explicit_bounded_context(self):
        for kind in ('local_safety_observation', 'blind_run_cue'):
            result = command_error_message(ControlError('old_epoch'),
                {'type': kind, 'controlEpoch': 7, 'text': 'private', 'evidence': {'map': 'private'}}, 8)
            self.assertEqual(result, {'type': 'error', 'error': 'old_epoch', 'requestType': kind,
                'submittedEpoch': 7, 'currentEpoch': 8, 'hasEpochContext': True})

    def test_operation_rejection_remains_distinguishable(self):
        for kind in ('resume', 'conversation_start', 'set_action', 'player_text'):
            result = command_error_message(ControlError('old_epoch'), {'type': kind, 'controlEpoch': 7}, 8)
            self.assertEqual(result['error'], 'old_epoch')
            self.assertEqual(result['requestType'], kind)
            self.assertNotIn(result['requestType'], ('local_safety_observation', 'blind_run_cue'))

    def test_missing_invalid_or_unbounded_context_is_not_classified(self):
        plain = {'type': 'error', 'error': 'old_epoch'}
        for epoch in (None, True, '7', -1, 2**31):
            self.assertEqual(command_error_message(ControlError('old_epoch'),
                {'type': 'blind_run_cue', 'controlEpoch': epoch}, 8), plain)
        for event in (None, [], {'type': 'arbitrary private text', 'controlEpoch': 7}):
            self.assertEqual(command_error_message(ControlError('old_epoch'), event, 8), plain)
        self.assertEqual(command_error_message(ControlError('old_epoch'),
            {'type': 'blind_run_cue', 'controlEpoch': 7}, True), plain)

    def test_non_epoch_error_shape_unchanged(self):
        event = {'type': 'blind_run_cue', 'controlEpoch': 7}
        self.assertEqual(command_error_message(ControlError('brain_stale'), event, 8),
                         {'type': 'error', 'error': 'brain_stale'})
        self.assertEqual(command_error_message(ValueError('private parser detail'), event, 8),
                         {'type': 'error', 'error': 'invalid_message'})


if __name__ == '__main__':
    unittest.main()
