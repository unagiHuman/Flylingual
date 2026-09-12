"""Observed neural state -> evidence for dialogue, never emotion detection."""
import math
from .control import ACTIONS


_MESSAGES = {
    'ja': {
        'unknown': '現在の脳活動は不明です。', 'invalid': '脳活動データが不正です。',
        'forward': '前進出力が出ています', 'right': '右旋回出力が出ています',
        'left': '左旋回出力が出ています', 'rest': '運動出力はゼロ付近です',
        'body_unknown': '身体の移動は未確認です。',
        'disclosure': '気持ちは観測に基づく擬人的表現で、感情測定ではありません。',
        'submitted': '刺激変更を送信しました。神経応答・身体動作はまだ未確認です。',
        'applied': 'Brainの刺激設定への適用を確認。身体動作は未確認です。',
        'intent_sent': '刺激の変更を送信しました。Brainへの適用と神経応答はこの後の観測で確認します。',
        'clarify': '指示が曖昧、または対応外です。停止・前進・左右旋回のどれかを明確に指定してください。操作していません。',
        'rejected': '操作していません。制御権・接続・期限・出力抑止を確認してください。',
        'incomplete_utterance': '新しい完全なプレイヤー発話を確認できません。操作していません。',
        'target_changed': 'Brain接続先を切替済み。旧targetの情報は過去情報です。新しい観測まで操作・反応は不明です。',
    },
    'en': {
        'unknown': 'Current brain activity is unknown.', 'invalid': 'Brain activity data is invalid.',
        'forward': 'Forward output is present', 'right': 'Right-turn output is present',
        'left': 'Left-turn output is present', 'rest': 'Motor output is near zero',
        'body_unknown': 'Body movement has not been verified.',
        'disclosure': 'Feelings are anthropomorphic expressions based on observations, not measured emotions.',
        'submitted': 'Stimulation change sent. Neural response and body movement are not yet verified.',
        'applied': 'Application to Brain stimulation confirmed. Body movement is unverified.',
        'intent_sent': 'Stimulation change sent. Subsequent observations will confirm Brain application and neural response.',
        'clarify': 'The request is unclear or unsupported. Please specify stop, forward, left or right. No action was taken.',
        'rejected': 'No action was taken. Check control ownership, connection, expiry and output inhibition.',
        'incomplete_utterance': 'No new complete player utterance was available. No action was taken.',
        'target_changed': 'The Brain target has changed. Old-target information is historical; response is unknown until new observations arrive.',
    },
}


def message_text(key, language='ja'):
    return _MESSAGES[language][key]


def summarize(frame, age_ms, stale_ms=750, language='ja'):
    text = lambda key: message_text(key, language)
    if not frame or age_ms is None or age_ms > stale_ms:
        return {'stale': True, 'interpretation': text('unknown'), 'facts': {}}
    motor = frame.get('motor', {})
    f, t = motor.get('forward'), motor.get('turn')
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in (f, t)):
        return {'stale': True, 'interpretation': text('invalid'), 'facts': {}}
    states = []
    if f > .02:
        states.append(text('forward'))
    if t > .02:
        states.append(text('right'))
    elif t < -.02:
        states.append(text('left'))
    if not states:
        states.append(text('rest'))
    raw = frame.get('raw', {})
    facts = {'forward': f, 'turn': t, 'brainTimeMs': frame.get('brainTimeMs'),
             'populationDeltaMv': raw.get('populationDeltaMv'),
             'forwardRaw': raw.get('forward_raw'), 'turnRaw': raw.get('turn_raw'),
             'filteredRaw': raw.get('filteredRaw'), 'neuronRates': frame.get('brain', {}),
             'backend': frame.get('metadata', {}).get('backendId'),
             'mode': frame.get('metadata', {}).get('mode'),
             'bodyMovementVerified': False}
    return {'stale': False, 'sequence': frame.get('sequence'), 'facts': facts,
            'interpretation': ('、' if language == 'ja' else ', ').join(states)
                + ('。' if language == 'ja' else '. ') + text('body_unknown'),
            'disclosure': text('disclosure')}


def mock_intent(text, default_ms, language='ja'):
    """Explicit mock only; exact phrases, not a substitute for GPT-Live."""
    phrases = {'止まって': 'STOP', '停止': 'STOP', '前へ': 'FORWARD', '前に進んで': 'FORWARD',
               '右に曲がって': 'TURN_R', '左に曲がって': 'TURN_L',
               '右前に進んで': 'FORWARD_R', '左前に進んで': 'FORWARD_L',
               'stop': 'STOP', 'go forward': 'FORWARD', 'move forward': 'FORWARD',
               'turn right': 'TURN_R', 'turn left': 'TURN_L',
               'go forward right': 'FORWARD_R', 'go forward left': 'FORWARD_L'}
    action = phrases.get(text.strip().lower(), text.strip().upper())
    if action in ACTIONS:
        return {'kind': 'action', 'action': action, 'validForMs': default_ms,
                'reply': 'MOCK: ' + ('操作提案を作成しました。適用はまだ未確認です。' if language == 'ja' else 'Action proposed; application is not yet verified.')}
    questions = {'今どんな気持ち？', '今どうなってる？', '脳の状態を教えて', '状態を教えて', 'how do you feel?', 'what is the brain doing?'}
    return {'kind': 'question' if text.strip().lower() in questions else 'clarify',
            'action': None, 'validForMs': default_ms,
            'reply': 'MOCK: ' + ('観測の質問または未対応入力です。操作していません。' if language == 'ja' else 'Observation question or unsupported input. No action taken.')}
