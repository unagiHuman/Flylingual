"""Game-authored course hint. Never a neural observation or a motor value."""
import math
import time

from .control import ControlError


class GoalRouteHint:
    def __init__(self):
        self.sequence = 0
        self.scope = None
        self.action = None
        self.at = 0.0

    def accept(self, event, epoch, generation, now=None):
        fields = {'type', 'controlEpoch', 'conversationGeneration', 'sequence', 'ageMs', 'action'}
        if set(event) != fields or event['type'] != 'goal_route_hint':
            raise ControlError('invalid_goal_route_hint')
        if (type(event['controlEpoch']) is not int or event['controlEpoch'] != epoch
                or type(event['conversationGeneration']) is not int or event['conversationGeneration'] != generation):
            raise ControlError('old_epoch')
        scope = (epoch, generation)
        age, seq, action = event['ageMs'], event['sequence'], event['action']
        if (type(seq) is not int or not 0 < seq <= 2**53
                or (scope == self.scope and seq <= self.sequence)
                or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age < 750
                or action not in (None, 'STOP', 'FORWARD', 'TURN_L', 'TURN_R', 'FORWARD_L', 'FORWARD_R')):
            raise ControlError('invalid_goal_route_hint')
        self.scope, self.sequence, self.action = scope, seq, action
        self.at = (time.monotonic() if now is None else now) - age / 1000

    def current(self, epoch, generation, now=None):
        stamp = time.monotonic() if now is None else now
        if self.scope != (epoch, generation) or not 0 <= stamp - self.at < .75:
            return None
        return self.action if self.action != 'STOP' else None

    def proposal(self, original, epoch, generation, max_ms, now=None):
        action = self.current(epoch, generation, now)
        if original['kind'] != 'clarify' or not action:
            return None
        return {'kind': 'action', 'action': action, 'plan': None,
                'operation': 'new', 'executionMode': 'timed', 'targetExecutionId': None,
                'distanceMeters': None, 'validForMs': min(max_ms, 6000),
                'reply': "I'll try a little farther along the path."}
