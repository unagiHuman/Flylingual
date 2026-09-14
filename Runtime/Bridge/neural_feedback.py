"""Bounded presentation only. Never called to choose or submit an Action."""
import math


SPONTANEOUS = {'RESPONSE_PRESENT', 'RESPONSE_CHANGED', 'POST_STOP_RESIDUAL', 'MOTOR_BODY_DISCREPANCY'}


def compact_summary(event, language='ja', *, question=False, no_sarcasm=False):
    """Whole sentences, Python character count, identical evidence across personas."""
    ja = language == 'ja'
    lead = ('最新の質問に答える。一般質問には普通に答える。' if ja else
            'Answer the latest question; answer general topics normally. ') if question else ''
    if not event or not event.get('fresh') or event.get('outputInhibited'):
        facts = ('現在の有効な神経観測は不明。身体動作も未確認。感情や拒否を測定したとは言わない。' if ja else
                 'Current usable neural observation is unavailable. Body movement is unverified. Emotions or refusal were not measured. ')
        return lead + facts
    current = event.get('current') or {}
    claims = set(event.get('allowedClaims') or [])
    facts = []
    if 'motor_body_discrepancy' in claims:
        facts.append('猶予後も対応motorと身体速度の差を観測。' if ja else 'After the calibrated grace period, matched motor and body velocity disagree. ')
    if 'stimulus_applied' in claims:
        action = current.get('observedAction')
        if action in ('STOP', 'FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L'):
            facts.append((action + 'の刺激適用を確認。') if ja else (action + ' stimulation application confirmed. '))
    if 'response_changed_observed_only' in claims:
        facts.append('同条件の前回と選択VNC応答の差を観測。' if ja else 'Selected VNC response differs from an eligible previous window. ')
    elif 'selected_direction_response' in claims:
        facts.append('選択VNCに指示方向の応答を検出。' if ja else 'Selected VNC response detected in the requested direction. ')
    layer = event.get('residualLayer')
    if 'post_stop_' + str(layer) in claims:
        names = {'decoder': ('デコーダ', 'decoder'), 'selected_neural_readout': ('選択神経読み出し', 'selected neural readout'), 'both': ('選択神経読み出しとデコーダ', 'selected neural readout and decoder')}
        if layer in names:
            facts.append(('STOP後も' + names[layer][0] + 'に残留出力。') if ja else ('Post-STOP residual in ' + names[layer][1] + '. '))
    # Numeric body observations do not establish causation or settled stopping.
    body = event.get('body') or {}
    measured = body.get('fresh') and body.get('correlated')
    facts.append(('身体は相関した速度の測定のみ。停止・操作の成功は未確定。' if measured else '身体の動作・停止は未確認。') if ja else
                 ('Body velocity sampled with frame correlation; stopping/action success unverified. ' if measured else 'Body movement/stopping unverified. '))
    facts.append('原因は未確定。感情・拒否・神経全体の静止を示す測定ではない。' if ja else
                 'Cause unknown; no measurement of emotion, refusal, or whole-brain silence. ')
    suffix = ('敬語なしで短く。' if ja else 'Keep it brief. ')
    if no_sarcasm:
        suffix += '皮肉なし。' if ja else 'No sarcasm. '
    value = lead + ''.join(facts) + suffix
    extras = []
    raw = current.get('raw') or {}
    motor = current.get('motor') or {}
    def numeric(group):
        vals = [group.get(axis) for axis in ('forward', 'turn')]
        return ','.join(format(v, '.3g') for v in vals) if all(type(v) in (int, float) and math.isfinite(v) for v in vals) else None
    for label, group in (('VNC raw mV f,t=', raw), ('motor f,t=', motor)):
        nums = numeric(group)
        if nums is not None:
            extras.append(label + nums + '. ')
    for extra in extras:
        if len(value + extra) <= 380:
            value += extra
    # All fixed core sentence combinations are checked by tests; no slicing.
    if len(value) > 380:
        value = lead + facts[-2] + facts[-1] + suffix
    assert len(value) <= 380
    return value


class NeuralFeedbackScheduler:
    """One replaceable pending observation; the Bridge owns the single consumer."""
    def __init__(self, config=None):
        config = config or {}
        self.spontaneous = config.get('spontaneousEnabled', True)
        self.cooldown_ms = config.get('cooldownMs', 4000)
        self.reduced = False
        self.no_sarcasm = False
        self.reset()

    def reset(self):
        self.pending = None
        self.last_sent_ms = -1e15
        self.blocked_until_ms = 0
        self.last_dedup = None
        self.replaced = 0

    def interrupt(self, now_ms, duration_ms=1500):
        self.pending = None
        self.blocked_until_ms = max(self.blocked_until_ms, now_ms + duration_ms)

    def preference(self, text):
        if not isinstance(text, str):
            return
        normalized = ''.join(text.lower().split())
        if any(term in normalized for term in ('実況減ら', '実況を減ら', '実況やめ', '実況をやめ', 'lesscommentary', 'stopcommentary', 'lessnarration')):
            self.reduced = True
            self.pending = None
        if any(term in normalized for term in ('皮肉やめ', '皮肉をやめ', '皮肉はやめ', '皮肉なし', 'nosarcasm', 'stopsarcasm')):
            self.no_sarcasm = True

    def offer(self, event):
        if self.pending is not None:
            self.replaced += 1
        self.pending = event

    def take(self, now_ms, *, epoch, generation, request_id, session_id, inhibited, chat_only, busy):
        event, self.pending = self.pending, None
        if not event:
            return None, 'empty'
        current = event.get('current') or {}
        if (event.get('controlEpoch') != epoch or event.get('conversationGeneration') != generation
                or (event.get('identity') or {}).get('sessionId') != session_id
                or current.get('requestedRequestId') != request_id):
            return None, 'superseded'
        expiry = event.get('expiresAt')
        if (not event.get('fresh') or type(expiry) not in (int, float) or not math.isfinite(expiry)
                or type(now_ms) not in (int, float) or not math.isfinite(now_ms) or now_ms > expiry):
            return None, 'stale'
        if inhibited or chat_only:
            return None, 'inhibited_or_chat_only'
        if busy or now_ms < self.blocked_until_ms:
            return None, 'higher_priority'
        if not self.spontaneous or self.reduced or event.get('eventType') not in SPONTANEOUS:
            return None, 'not_allowlisted_or_disabled'
        if now_ms - self.last_sent_ms < self.cooldown_ms:
            return None, 'cooldown'
        key = event.get('dedupKey')
        if key == self.last_dedup:
            return None, 'duplicate'
        self.last_dedup, self.last_sent_ms = key, now_ms
        return event, None
