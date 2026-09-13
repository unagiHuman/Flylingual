"""Deterministic control authority. No neural or motor calculations."""
import math
import time
from collections import deque

ACTIONS = ('STOP', 'FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L')


class ControlError(ValueError):
    pass


class ControlArbiter:
    def __init__(self, config):
        self.owner = config['owner']
        self.max_ms = config['maxActionMs']
        self.epoch = 1
        self.inhibited = True
        self.reason = 'explicit_resume_required'
        self.deadline = None
        self.seen = set()
        self.order = deque()

    def inhibit(self, reason, new_epoch=True):
        self.inhibited = True
        self.reason = reason
        self.deadline = None
        if new_epoch:
            self.epoch += 1

    def set_owner(self, owner):
        if owner not in ('manual', 'gpt', 'observer'):
            raise ControlError('invalid_owner')
        self.owner = owner
        self.inhibit('owner_changed')

    def resume(self):
        if self.owner == 'observer':
            raise ControlError('observer_cannot_control')
        self.inhibited = False
        self.reason = ''

    def accept(self, source, action, command_id, epoch, valid_ms, *, execution_mode='timed'):
        if source != self.owner or source == 'observer':
            raise ControlError('not_control_owner')
        if type(epoch) is not int or epoch != self.epoch:
            raise ControlError('old_control_epoch')
        if self.inhibited:
            raise ControlError('output_inhibited')
        if action not in ACTIONS:
            raise ControlError('invalid_action')
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 128:
            raise ControlError('invalid_command_id')
        if command_id in self.seen:
            raise ControlError('duplicate_command')
        # Check the bounded range before float conversion (huge JSON integers).
        if execution_mode == 'until_next_command':
            if source != 'gpt' or action == 'STOP' or valid_ms is not None:
                raise ControlError('invalid_command_duration')
        elif execution_mode != 'timed' or (type(valid_ms) not in (int, float)
                or not 0 < valid_ms <= self.max_ms or not math.isfinite(valid_ms)):
            raise ControlError('invalid_command_duration')
        self.seen.add(command_id)
        self.order.append(command_id)
        if len(self.order) > 4096:
            self.seen.remove(self.order.popleft())
        self.deadline = (None if action == 'STOP' or execution_mode == 'until_next_command'
                         else time.monotonic() + valid_ms / 1000)

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline
