"""Pure route-envelope/admission contracts; no Brain or simulated gameplay."""
import unittest
from Runtime.Bridge.goal_route import GoalRouteHint
from Runtime.Bridge.control import ControlError


class GoalRouteTests(unittest.TestCase):
    def event(self, **extra):
        return {'type': 'goal_route_hint', 'controlEpoch': 2, 'conversationGeneration': 3,
                'sequence': 1, 'ageMs': 0, 'action': 'FORWARD', **extra}

    def test_only_current_scope_fresh_hint_can_supply_bounded_action(self):
        hint = GoalRouteHint()
        hint.accept(self.event(), 2, 3, now=100)
        self.assertEqual(hint.proposal({'kind': 'clarify'}, 2, 3, 8000, now=100.1)['validForMs'], 6000)
        self.assertIsNone(hint.proposal({'kind': 'question'}, 2, 3, 8000, now=100.1))
        self.assertIsNone(hint.current(3, 3, now=100.1))
        self.assertIsNone(hint.current(2, 4, now=100.1))
        self.assertIsNone(hint.current(2, 3, now=100.75))

    def test_null_and_stop_do_not_start_movement(self):
        for action in (None, 'STOP'):
            hint = GoalRouteHint()
            hint.accept(self.event(action=action), 2, 3, now=100)
            self.assertIsNone(hint.proposal({'kind': 'clarify'}, 2, 3, 8000, now=100))

    def test_invalid_and_replayed_hints_rejected(self):
        for extra in ({'action': 'TELEPORT'}, {'ageMs': float('nan')}, {'sequence': True}, {'ageMs': 750}):
            with self.assertRaises(ControlError):
                GoalRouteHint().accept(self.event(**extra), 2, 3, now=100)
        hint = GoalRouteHint()
        hint.accept(self.event(), 2, 3, now=100)
        with self.assertRaises(ControlError):
            hint.accept(self.event(), 2, 3, now=100.1)
