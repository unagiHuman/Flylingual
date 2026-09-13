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
    if (not isinstance(result, dict) or set(result) != keys
            or not isinstance(result['kind'], str)
            or result['kind'] not in ('action', 'plan', 'question', 'clarify')
            or type(result['validForMs']) is not int or not 0 < result['validForMs'] <= max_ms
            or not isinstance(result['reply'], str) or len(result['reply']) > 1000):
        raise ControlError('invalid_intent')
    kind, action, plan = result['kind'], result['action'], result['plan']
    if kind == 'action':
        valid = isinstance(action, str) and action in ACTIONS and plan is None
    elif kind == 'plan':
        valid = action is None and isinstance(plan, str) and plan in PLAN_STEPS
    else:
        valid = action is None and plan is None
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
        if time.monotonic() >= deadline:
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

    async def begin(self, name, command_id, epoch, generation, deadline):
        reason = self.guard(epoch, generation, deadline)
        if reason:
            raise ControlError(reason)
        replaced = self.active is not None
        try:
            await self.cancel_and_wait()
        except asyncio.CancelledError:
            if replaced:
                await self.bridge.inhibit('plan_replacement_cancelled')
            raise
        reason = self.guard(epoch, generation, deadline)
        if reason:
            if replaced:
                await self.bridge.inhibit('plan_replacement_failed')
            raise ControlError(reason)
        plan = {'planId': 'plan-' + str(uuid.uuid4()), 'commandId': command_id,
                'name': name, 'step': 0, 'requestId': None, 'deadline': deadline}
        self.active = plan
        self.bridge.log('plan_started', planId=plan['planId'], commandId=command_id, name=name)
        self.task = self.bridge.task(self.run(plan, epoch, generation))

    async def run(self, plan, epoch, generation):
        b = self.bridge
        applied_at = None
        phase_sent = False
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
                if not phase_sent:
                    action = steps[plan['step']]
                    command_id = plan['planId'] + '-' + str(plan['step'])
                    remaining_ms = (plan['deadline'] - time.monotonic()) * 1000
                    b.arbiter.accept('gpt', action, command_id, epoch, remaining_ms)
                    plan['requestId'] = await b.submit(action, 'gpt', command_id)
                    phase_sent = True
                    b.log('plan_step_submitted', planId=plan['planId'], step=plan['step'],
                          requestId=plan['requestId'], action=action)
                item = b.requests.get(plan['requestId'], {})
                if item.get('rejected') or item.get('superseded'):
                    await b.inhibit('plan_step_not_applied')
                    return
                if item.get('applied'):
                    if applied_at is None:
                        applied_at = time.monotonic()
                    short_turn = (len(steps) == 2 and plan['step'] == 0) or plan['name'].startswith('nudge_')
                    if short_turn and time.monotonic() - applied_at >= .5:
                        if plan['step'] + 1 == len(steps):
                            await b.finish_plan(plan, 'plan_finished')
                            return
                        plan['step'] += 1
                        phase_sent = False
                        applied_at = None
                        continue  # Recheck observations/ownership before the next Action.
                await asyncio.sleep(.05)
        except asyncio.CancelledError:
            raise  # Cancellation is paired with replacement or the existing inhibit path.
        except Exception:
            b.log('plan_stopped', planId=plan['planId'], reason='plan_execution_failed')
            if self.active is plan:
                await b.inhibit('plan_execution_failed')
        finally:
            if self.active is plan:
                self.active = self.task = None
