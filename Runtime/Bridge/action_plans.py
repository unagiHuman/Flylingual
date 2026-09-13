"""Bounded linguistic plan presets and local hazard checks, never motor values."""
import asyncio
import time
import uuid

from .control import ACTIONS, ControlError


PLAN_STEPS = {
    'forward_until_concern': ('FORWARD',),
    'right_then_forward': ('TURN_R', 'FORWARD'),
    'left_then_forward': ('TURN_L', 'FORWARD'),
    'nudge_right': ('TURN_R',),
    'nudge_left': ('TURN_L',),
}
PLAN_REPLY = {
    'ja': {
        'forward_until_concern': '端や危険を感じたら、止まるね。',
        'right_then_forward': '少し右を向いて、進むね。',
        'left_then_forward': '少し左を向いて、進むね。',
        'nudge_right': '少し右を向くね。', 'nudge_left': '少し左を向くね。',
    },
    'en': {
        'forward_until_concern': "I'll stop at an edge or hazard.",
        'right_then_forward': "I'll turn a little right, then move forward.",
        'left_then_forward': "I'll turn a little left, then move forward.",
        'nudge_right': "I'll turn a little right.", 'nudge_left': "I'll turn a little left.",
    },
}


def validate_intent(result, max_ms):
    """Validate the complete model proposal before any authority is consulted."""
    keys = {'kind', 'action', 'plan', 'validForMs', 'reply'}
    extension = {'operation', 'executionMode', 'targetExecutionId'}
    if (not isinstance(result, dict) or set(result) not in (keys, keys | extension)
            or not isinstance(result['kind'], str)
            or result['kind'] not in ('action', 'plan', 'question', 'clarify', 'update')
            or not isinstance(result['reply'], str) or len(result['reply']) > 1000):
        raise ControlError('invalid_intent')
    kind, action, plan = result['kind'], result['action'], result['plan']
    operation = result.get('operation', 'new')
    mode = result.get('executionMode', 'timed')
    target = result.get('targetExecutionId')
    duration = result['validForMs']
    timed = type(duration) is int and 0 < duration <= max_ms
    if (mode not in ('timed', 'until_next_command', 'inherit')
            or (mode == 'timed' and not timed)
            or (mode != 'timed' and duration is not None)):
        raise ControlError('invalid_intent')
    if kind == 'update':
        valid = (set(result) == keys | extension and action is None and plan is None
                 and operation in ('continue', 'modify_conditions')
                 and isinstance(target, str) and 1 <= len(target) <= 128
                 and target.strip() != ''
                 and (operation != 'modify_conditions' or mode == 'inherit'))
        if not valid:
            raise ControlError('invalid_intent')
        return result
    if operation != 'new' or target is not None or mode == 'inherit':
        raise ControlError('invalid_intent')
    if kind == 'action':
        valid = (isinstance(action, str) and action in ACTIONS and plan is None
                 and (action != 'STOP' or mode == 'timed'))
    elif kind == 'plan':
        valid = (action is None and isinstance(plan, str) and plan in PLAN_STEPS
                 and (not plan.startswith('nudge_') or mode == 'timed'))
    else:
        valid = action is None and plan is None and mode == 'timed'
    if not valid:
        raise ControlError('invalid_intent')
    return result


class LocalSafetyObservation:
    """One bounded, fail-closed snapshot; sequence is scoped to the control epoch."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.sequence = 0
        self.sample = None
        self.sample_at = 0

    def accept(self, event, now=None):
        fields = {'type', 'controlEpoch', 'conversationGeneration', 'sequence', 'ageMs',
                  'groundPresent', 'leftEdge', 'rightEdge', 'forwardBlocked', 'bodyUnsafe'}
        if set(event) != fields:
            raise ControlError('invalid_local_observation')
        if (type(event['sequence']) is not int or not self.sequence < event['sequence'] <= 2**53
                or type(event['ageMs']) not in (int, float) or not 0 <= event['ageMs'] <= 750
                or any(type(event[k]) is not bool for k in ('groundPresent', 'forwardBlocked', 'bodyUnsafe'))
                or any(not isinstance(event[k], str) or event[k] not in ('safe', 'near', 'very_near', 'unknown')
                       for k in ('leftEdge', 'rightEdge'))):
            raise ControlError('invalid_or_stale_local_observation')
        self.sequence = event['sequence']
        self.sample = {k: event[k] for k in ('groundPresent', 'leftEdge', 'rightEdge', 'forwardBlocked', 'bodyUnsafe')}
        self.sample_at = (time.monotonic() if now is None else now) - event['ageMs']/1000

    def concern(self, now=None):
        now = time.monotonic() if now is None else now
        if self.sample is None or now - self.sample_at >= .75:
            return 'local_observation_unavailable'
        s = self.sample
        if s['leftEdge'] == 'unknown' or s['rightEdge'] == 'unknown':
            return 'local_observation_unknown'
        if not s['groundPresent']:
            return 'ground_missing'
        # Stop early at NEAR, not just VERY_NEAR: normal STOP has residual motion.
        if s['leftEdge'] in ('near', 'very_near') or s['rightEdge'] in ('near', 'very_near'):
            return 'edge_near'
        if s['forwardBlocked']:
            return 'forward_blocked'
        if s['bodyUnsafe']:
            return 'body_unsafe'
        return None

    def summary(self, now=None):
        """A small local-only view; expired values must not reach the interpreter."""
        now = time.monotonic() if now is None else now
        age = max(0, (now - self.sample_at) * 1000) if self.sample is not None else None
        fresh = age is not None and age < 750
        return {'source': 'unity_local_sensors', 'sequence': self.sequence,
                'ageMs': round(age, 1) if age is not None else None,
                'fresh': fresh, 'concern': self.concern(now),
                'facts': dict(self.sample) if fresh else {}}


class BoundedPlanRunner:
    """One sequential plan. The existing arbiter and STOP/inhibit remain authoritative."""
    def __init__(self, bridge):
        self.bridge = bridge
        self.active = None
        self.task = None

    def cancel(self):
        task = self.task
        self.active = self.task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return task

    async def cancel_and_wait(self):
        task = self.cancel()
        if task is not None and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)

    def guard(self, epoch, generation, deadline):
        b = self.bridge
        if deadline is not None and time.monotonic() >= deadline:
            return 'plan_expired'
        if epoch != b.arbiter.epoch or generation != b.conversation_generation:
            return 'plan_old_generation'
        if (b.closed or b.control_ws is None or b.switching or b.release_unknown
                or not b.conversation_accepting or b.conversation.state != 'live'
                or b.conversation_interaction != 'control'):
            return 'plan_connection_unavailable'
        if b.arbiter.inhibited or b.arbiter.owner != 'gpt':
            return 'plan_control_unavailable'
        if not b.adapter or not b.adapter.connected or b.summary()['stale']:
            return 'plan_brain_stale'
        return b.local_observation.concern()

    def admission_reason(self, epoch, generation, intent_deadline, revision):
        if revision != self.bridge.intent_revision:
            return 'stale_intent'
        if time.monotonic() >= intent_deadline:
            return 'expired_intent'
        return self.guard(epoch, generation, intent_deadline)

    async def begin(self, name, command_id, epoch, generation, duration_ms, *, intent_deadline, revision,
                    execution_mode='timed', delegation_id=None, admission_check=None, notify_live=False):
        if not isinstance(name, str) or name not in PLAN_STEPS:
            raise ControlError('invalid_intent')
        if (execution_mode not in ('timed', 'until_next_command')
                or (execution_mode == 'timed' and (type(duration_ms) is not int
                    or not 0 < duration_ms <= self.bridge.config['control']['maxActionMs']))
                or (execution_mode == 'until_next_command'
                    and (duration_ms is not None or name.startswith('nudge_')))):
            raise ControlError('invalid_command_duration')
        reason = self.admission_reason(epoch, generation, intent_deadline, revision)
        if reason:
            raise ControlError(reason)
        if admission_check is not None:
            admission_check()
        replaced = self.active is not None
        try:
            await self.cancel_and_wait()
        except asyncio.CancelledError:
            if replaced:
                await self.bridge.inhibit('plan_replacement_cancelled')
            raise
        reason = self.admission_reason(epoch, generation, intent_deadline, revision)
        if reason:
            if replaced:
                await self.bridge.inhibit('plan_replacement_failed')
            raise ControlError(reason)
        if admission_check is not None:
            try:
                admission_check()
            except ControlError:
                if replaced:
                    await self.bridge.inhibit('plan_replacement_failed')
                raise
        deadline = time.monotonic() + duration_ms/1000 if execution_mode == 'timed' else None
        plan = {'planId': 'plan-' + str(uuid.uuid4()), 'commandId': command_id,
                'executionId': command_id, 'executionMode': execution_mode, 'delegationId': delegation_id,
                'notifyLive': notify_live,
                'name': name, 'step': 0, 'requestId': None, 'deadline': deadline,
                'phaseSent': False, 'appliedAt': None, 'submittedAt': None, 'applyDeadline': None}
        self.bridge.activate_execution(command_id, PLAN_STEPS[name][0], execution_mode, deadline,
                                       plan=name, monitor_hazards=True)
        self.active = plan
        self.bridge.log('plan_started', planId=plan['planId'], commandId=command_id, name=name,
                        executionDurationMs=duration_ms)
        self.task = self.bridge.task(self.run(plan, epoch, generation))

    async def run(self, plan, epoch, generation):
        b = self.bridge
        try:
            while self.active is plan:
                reason = self.guard(epoch, generation, plan['deadline'])
                if reason:
                    if reason == 'plan_expired':
                        await b.finish_plan(plan, reason)
                        return
                    b.log('plan_stopped', planId=plan['planId'], reason=reason)
                    await b.inhibit(reason)
                    return
                steps = PLAN_STEPS[plan['name']]
                if not plan['phaseSent']:
                    action = steps[plan['step']]
                    command_id = plan['planId'] + '-' + str(plan['step'])
                    remaining_ms = ((plan['deadline'] - time.monotonic()) * 1000
                                    if plan['deadline'] is not None else None)
                    b.arbiter.accept('gpt', action, command_id, epoch, remaining_ms,
                                     execution_mode=plan['executionMode'])
                    b.update_execution_step(plan['executionId'], action, plan['step'])
                    plan['submittedAt'] = time.monotonic()
                    timeout = b.config['control']['stopTimeoutMs']/1000
                    plan['applyDeadline'] = plan['submittedAt'] + timeout
                    delegation = ({'delegation_id': plan['delegationId']} if plan['delegationId'] is not None else {})
                    if plan['notifyLive']:
                        delegation['notify_live'] = True
                    plan['requestId'] = await asyncio.wait_for(b.submit(action, 'gpt', command_id, **delegation), timeout)
                    if self.active is not plan:
                        return
                    plan['phaseSent'] = True
                    b.log('plan_step_submitted', planId=plan['planId'], step=plan['step'],
                          requestId=plan['requestId'], action=action)
                item = b.requests.get(plan['requestId'], {})
                if item.get('rejected') or item.get('superseded'):
                    await b.inhibit('plan_step_not_applied')
                    return
                if plan['appliedAt'] is None and time.monotonic() >= plan['applyDeadline']:
                    await b.inhibit('plan_apply_timeout')
                    return
                if item.get('applied'):
                    if plan['appliedAt'] is None:
                        plan['appliedAt'] = time.monotonic()
                    short_turn = (len(steps) == 2 and plan['step'] == 0) or plan['name'].startswith('nudge_')
                    if short_turn and time.monotonic() - plan['appliedAt'] >= .5:
                        if plan['step'] + 1 == len(steps):
                            await b.finish_plan(plan, 'plan_finished')
                            return
                        plan['step'] += 1
                        plan['phaseSent'] = False
                        plan['appliedAt'] = None
                        continue  # Recheck observations/ownership before the next Action.
                await asyncio.sleep(.05)
        except asyncio.CancelledError:
            raise  # Cancellation is paired with replacement or the existing inhibit path.
        except (asyncio.TimeoutError, TimeoutError):
            if self.active is plan:
                await b.inhibit('plan_submit_timeout')
        except Exception:
            b.log('plan_stopped', planId=plan['planId'], reason='plan_execution_failed')
            if self.active is plan:
                await b.inhibit('plan_execution_failed')
        finally:
            if self.active is plan:
                self.active = self.task = None
