"""Observed neural state -> evidence for dialogue, never emotion detection."""
import math
from .control import ACTIONS


def summarize(frame, age_ms, stale_ms=750):
    if not frame or age_ms is None or age_ms > stale_ms:
        return {'stale': True, 'interpretation': '現在の脳活動は不明です。', 'facts': {}}
    motor = frame.get('motor', {})
    f, t = motor.get('forward'), motor.get('turn')
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in (f, t)):
        return {'stale': True, 'interpretation': '脳活動データが不正です。', 'facts': {}}
    states = []
    if f > .02:
        states.append('前進出力が出ています')
    if t > .02:
        states.append('右旋回出力が出ています')
    elif t < -.02:
        states.append('左旋回出力が出ています')
    if not states:
        states.append('運動出力はゼロ付近です')
    raw = frame.get('raw', {})
    facts = {'forward': f, 'turn': t, 'brainTimeMs': frame.get('brainTimeMs'),
             'populationDeltaMv': raw.get('populationDeltaMv'),
             'forwardRaw': raw.get('forward_raw'), 'turnRaw': raw.get('turn_raw'),
             'filteredRaw': raw.get('filteredRaw'), 'neuronRates': frame.get('brain', {}),
             'backend': frame.get('metadata', {}).get('backendId'),
             'mode': frame.get('metadata', {}).get('mode'),
             'bodyMovementVerified': False}
    return {'stale': False, 'sequence': frame.get('sequence'), 'facts': facts,
            'interpretation': '、'.join(states) + '。身体の移動は未確認です。',
            'disclosure': '気持ちは観測に基づく擬人的表現で、感情測定ではありません。'}


def mock_intent(text, default_ms):
    """Explicit mock only; exact phrases, not a substitute for GPT-Live."""
    phrases = {'止まって': 'STOP', '停止': 'STOP', '前へ': 'FORWARD', '前に進んで': 'FORWARD',
               '右に曲がって': 'TURN_R', '左に曲がって': 'TURN_L',
               '右前に進んで': 'FORWARD_R', '左前に進んで': 'FORWARD_L'}
    action = phrases.get(text.strip(), text.strip().upper())
    if action in ACTIONS:
        return {'kind': 'action', 'action': action, 'validForMs': default_ms,
                'reply': 'MOCK: 操作提案を作成しました。適用はまだ未確認です。'}
    questions = {'今どんな気持ち？', '今どうなってる？', '脳の状態を教えて', '状態を教えて'}
    return {'kind': 'question' if text.strip() in questions else 'clarify',
            'action': None, 'validForMs': default_ms,
            'reply': 'MOCK: 観測の質問または未対応入力です。操作していません。'}
