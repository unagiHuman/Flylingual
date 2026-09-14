"""Bounded presentation only. Never called to choose or submit an Action."""
import math


SPONTANEOUS = {'RESPONSE_PRESENT', 'RESPONSE_CHANGED', 'POST_STOP_RESIDUAL', 'MOTOR_BODY_DISCREPANCY'}


def compact_summary(event, language='ja', *, question=False, no_sarcasm=False):
    """Budget whole sentences; facts never specify or replace the configured persona."""
    ja = language == 'ja'
    lead = ('最新の質問に普通に答える。' if ja else 'Answer the latest question normally. ') if question else ''
    style = '設定中の人格・口調を維持して短く。' if ja else 'Keep the configured persona and tone; be brief. '
    if no_sarcasm:
        style += '皮肉なし。' if ja else 'No sarcasm. '
    if not event or not event.get('fresh') or event.get('outputInhibited'):
        facts = ('現在の有効な神経観測は不明。身体動作も未確認。感情や拒否を測定したとは言わない。' if ja else
                 'Current usable neural observation is unavailable. Body movement is unverified. Emotions or refusal were not measured. ')
        return lead + facts + style
    current = event.get('current') or {}
    claims = set(event.get('allowedClaims') or [])
    changed = 'response_changed_observed_only' in claims
    facts = []
    if changed:
        # Axis facts are authoritative when present. Legacy summaries remain usable
        # without fabricating an axis from their old scalar comparison fields.
        comparison = event.get('comparison') or {}
        axes = comparison.get('axes') or {}
        changed_axes = comparison.get('changedAxes') or []
        action = current.get('observedAction')
        relevant = {'FORWARD': ('forward',), 'TURN_R': ('turn',), 'TURN_L': ('turn',),
                    'FORWARD_R': ('forward', 'turn'), 'FORWARD_L': ('forward', 'turn')}.get(action, ())
        selected = [axis for axis in relevant if axis in changed_axes
                    and isinstance(axes.get(axis), dict) and axes[axis].get('eligible') is True
                    and axes[axis].get('changed') is True]
        axis_text = ('（' + '・'.join('前進軸' if a == 'forward' else '旋回軸' for a in selected) + '）' if ja else
                     ' (' + ', '.join(selected) + ')') if selected else ''
        action_text = action if relevant else ('同一Action' if ja else 'same-Action')
        facts.append(('前回の比較可能な' + action_text + '観測と選択VNC応答に差' + axis_text + 'があります。') if ja else
                     ('Selected VNC response differs from a comparable previous ' + action_text + ' observation' + axis_text + '. '))
    if 'motor_body_discrepancy' in claims:
        facts.append('校正された猶予後も対応motorと身体速度の差を観測。' if ja else
                     'After calibrated grace, matched motor and body velocity disagree. ')
    layer = event.get('residualLayer')
    if 'post_stop_' + str(layer) in claims:
        names = {'decoder': ('デコーダ', 'decoder'), 'selected_neural_readout': ('選択VNC読み出し', 'selected VNC readout'),
                 'both': ('選択VNC読み出しとデコーダ', 'selected VNC readout and decoder')}
        if layer in names:
            facts.append(('STOP後も' + names[layer][0] + 'に残留出力。') if ja else ('Post-STOP residual in ' + names[layer][1] + '. '))
    if not changed and 'selected_direction_response' in claims:
        facts.append('選択VNCに指示方向の応答を検出。' if ja else 'Selected VNC response detected in the requested direction. ')
    if 'stimulus_applied' in claims:
        action = current.get('observedAction')
        if action in ('STOP', 'FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L'):
            facts.append((action + 'の刺激適用を確認。') if ja else (action + ' stimulation application confirmed. '))
    # Reserve the limits of interpretation before adding optional measurements.
    # DNg100/readoutHz is deliberately never used as downstream response evidence.
    cause = ('刺激の確率的変動を含むため原因は未確定。' if ja else
             'Cause unknown; stimulus variability was not excluded. ') if changed else ('原因は未確定。' if ja else 'Cause unknown. ')
    body = event.get('body') or {}
    measured = body.get('fresh') and body.get('correlated')
    verification = (('身体は相関した速度の測定のみ。停止・操作の成功は未確定。' if measured else '身体の動作・停止は未確認。') if ja else
                    ('Correlated body velocity only; action success unverified. ' if measured else 'Body movement/stopping unverified. '))
    limits = '感情・拒否・全脳の静止を示す測定ではない。' if ja else 'No emotion, refusal or whole-brain silence measured. '
    required = cause + verification + limits + style
    value = lead
    for fact in facts:
        if len(value + fact + required) <= 380:
            value += fact
    value += required
    def numeric(group):
        vals = [group.get(axis) for axis in ('forward', 'turn')]
        return ','.join(format(v, '.3g') for v in vals) if all(type(v) in (int, float) and math.isfinite(v) for v in vals) else None
    # Each detail is independent; omission never merges raw, decoder and motor layers.
    for label, group in (('VNC raw mV f,t=', current.get('raw') or {}),
                         ('filtered raw mV f,t=', current.get('filteredRaw') or {}),
                         ('motor f,t=', current.get('motor') or {})):
        nums = numeric(group)
        extra = label + nums + '. ' if nums is not None else ''
        if len(value + extra) <= 380:
            value += extra
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
