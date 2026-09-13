# 大まかな移動指示と条件付き停止

2026-09-13。ユーザー合意の「右側に進んで」「前進して、違和感があれば止まれ」を
Backendへ追加。完全な自律ナビゲーションではなく、短い既存Actionの計画である。
共通設計正本の制御境界を維持する。

## 対応する解釈

| 言葉の例 | 計画 | 動作要求 |
|---|---|---|
| 前に進んで、違和感があったら止まれ | forward_until_concern | FORWARD、危険または期限でSTOP |
| 右側に進んで | right_then_forward | TURN_R→FORWARD、危険または期限でSTOP |
| 左側に進んで | left_then_forward | TURN_L→FORWARD、危険または期限でSTOP |
| ちょっと右 | nudge_right | 短いTURN_R→STOP |
| ちょっと左 | nudge_left | 短いTURN_L→STOP |
| 右は危ない？／右がいいかな？ | question | 新しいActionなし |
| あそこへ／左右同時に／未対応条件 | clarify | 新しいActionなし、短く確認 |

「右のほうへお願い」「右へ進んでくれる？」も右旋回→前進、
「もう少し右」「Turn a touch left」は短い旋回として扱う。
「前へ様子を見ながら」は条件付き前進。「右、いや左」の明確な言い直しは最後の方向を使う。
一方、「右がいいかな？」は相談であり操作しない。
「そのまま進んで」「違和感があったら止まれ」だけの指示は、Bridgeの現在有効なGPT操作を根拠にする。
有効な操作がない、期限切れ、STOP済み、旧epochなら方向を短く確認する。
「砂糖まで」「安全な方へ」の経路決定は安全フラグだけから推測しない。

英語にも同じ5計画を定義。GPT Liveは音声とclient delegationを担当し、
Responsesが既存のJSON schemaで `kind=plan` と許可されたpresetを提案する。
ASR断片の自動実行、キーワードだけによるLive操作fallback、別APIへの自動切替は追加しない。
mock意図翻訳は従来の単純Actionのみで、新計画の音声認識成功を代替しない。

単純な「前に進んで」「止まって」は従来のkind=action経路を維持。
新しい危険監視はkind=planのみに適用する。通常Actionやmanual入力を勝手に置換しない。
新しい質問では既に実行中の計画を置き換えないため、以前の指示による動きは継続し得る。
止める場合は明確なSTOPまたは既存緊急停止を使用する。

## 違和感の定義

局所センサーsnapshotは以下だけ。地図、正解ルート、座標一覧、自由文章を受信しない。

- 左右端：safe / near / very_near / unknown。
- 足元の地面：groundPresent。
- 前方が塞がっている：forwardBlocked。
- 身体が危険状態：bodyUnsafe。

near以上、地面消失、前方障害、bodyUnsafeのいずれかでSTOP＋既存出力抑止。
unknown、欠損、750ms以上経過、不正snapshotでも停止・開始拒否。
bodyUnsafeは普通の歩行中の「stable=false」とは別。転倒等の危険をUnity側で判定する。
nearの実距離やbodyUnsafeの閾値は、実ハエとセンサーで検証する必要があり、ここでは捏造しない。

危険通知受信時はGPTを待たずBridgeで停止。加えて計画loopは50msごとに監視する。
この周期は実時間応答の保証ではない。イベントループ遅延、TCP、Brain計算、decoder余動が残る。
通常STOPで即時静止する保証はない。物理位置固定、velocityゼロ化、decoder変更は行わない。

## 実行期限と適用確認

- 既存defaultActionMs=4000、maxActionMs=8000を変更しない。端末設定が短ければその値を使う。
- Responses解釈の開始時から計画の絶対期限を計測し、API時間も差し引く。継続更新で期限を延長しない。
- 各段階は既存ControlArbiter.acceptとBridge.submit→BrainAdapterを通す。
- 最初のTURNのBrain適用（appliedRequestId）を確認してから500msの短い刺激区間を測る。
  その後FORWARDへ進むが、直前にも危険・期限・接続・世代を再確認する。
- nudgeも適用確認後500ms、または先に来る絶対期限で終了する。
- ACKだけ、適用なし、拒否／supersededでは次のActionへ進めない。
- 500msは刺激の区間であり、回転角・身体方向の達成保証ではない。閉ループ方位合わせは未実装。
- Native音声controlでは、新鮮で危険のない観測・Brain・操作権・音声接続が揃った通常の期限／計画完了はSTOPだけを送り、epoch・音声・motor TCPを維持する。次の新しい音声指示を受け付ける。自動で前の計画を再開することはない。
- 危険・古い観測・接続断・STOP送信失敗は既存inhibit＋STOP。Legacy非Nativeも従来の抑止を維持する。安全停止後の復旧は既存の明示再開／Native復旧手順に従い、旧計画は再送しない。

ハエは解釈を「少し右を向いて、進むね。」程度に返す。これは提案・開始の説明で、移動完了の宣言ではない。
観測がない場合は「周りがまだわからないから、進めない。」と短く答える。

## 競合・中断

計画は同時に1つ。新しいActionまたは新計画は旧計画taskをcancelして終了を待つ。
STOP後に旧FORWARDが再送されないようにする。置換処理そのものが失敗・cancelされた場合も停止側へ倒す。
control切断、GPT停止、Brain stale、owner切替、epoch/session変更、緊急停止、再接続で旧計画は破棄。
chat_only、observer、出力抑止中には開始できない。readyを変更しない。

## ファイルと通信

- `Runtime/Bridge/action_plans.py`：preset、厳密proposal検証、局所危険判定、単一計画実行器。
- `Runtime/Bridge/conversation.py`：既存Responses schemaにplanを追加。
- `Runtime/Bridge/conversation_prompts.py`：大まかな言い方を委任し、重大な曖昧さだけ確認。
- `Runtime/Bridge/server.py`：既存Action経路、観測受信、世代・中断処理へ接続。
- [bounded-action-plans-v1契約](../../Contracts/bridge-v1/bounded-action-plans-v1.md)。

## Unity地形センサーとの接続（2026-09-13）

`3377cf5`で追加された既存producerを再利用する。Unity側の新規実装・Scene変更は不要。
`FlyTerrainRuntime`→`ConversationSessionController.SendLocalSafetyObservation`→
既存control WebSocket→`Bridge.accept_local_observation`→計画の危険監視。
groundedTripodGaitリグへの自動追加、10Hz送信、UnityのFresh判定（250ms以内）、
overflow時のunknown変換は既存実装。[地形センサー仕様](../windows/Fly-Terrain-Sensing.md)を参照。

Bridgeは受信した5種類の安全観測を`localSafety`としてResponsesへ渡し、
周囲への質問にも新しい観測で答える。750ms以上の古いfactsは空にし、地形を捏造しない。
stateにはsequence／ageMs／fresh／concernが出る。初回・危険状態変化は
`local_observation_received`ログで確認できる。観測はBrainのfreshnessやreadyを更新しない。
Liveには意味が変わった観測だけを既存の2秒周期でthinkingへ渡す。センサー更新だけで長い説明を発話しない。
この会話用更新周期と、50msの計画監視・危険通知受信直後のSTOPは別処理。
安全フラグは全体地図・ランドマーク・進路・身体の移動完了を意味しない。

OpenAI Docsの[Live delegation](https://developers.openai.com/api/docs/guides/live-delegation)の
役割分担に従い、発話指示だけで中断済みとせず、Backend側が操作を管理する。

## 検証・残課題

オフライン検証：5preset、schema不正値、危険全条件、欠損／古い観測、適用なし／negative ACK、
右左の段階遷移、nudge、期限STOP、明示STOP置換、質問による非操作、
epoch／GPT停止／control切断／不正観測による中断をスタブで検証。
Brain freshnessとsensor freshnessは独立に試験する。構文とdiffも確認する。

今回の追加検証：既存Pythonテスト30件成功。5計画の通常STOP→次音声Action、
6種類の危険／unknownによる抑止、期限・STOP配信中の新指示の維持、質問による非操作、
古い観測の除外、Legacy／STOP送信失敗をオフラインのprotocol stubで確認。
これはUnityや実Brainの動作テストではない。

実Responses API（既存gpt-5.6-luna、store=false、日英の合成テキスト＋安全snapshot例）では、
初回18件中17件一致。「Turn a touch left」が通常TURN_Lになったため、
小さな旋回をnudge計画へ優先分類する指示に修正した。
修正版22件は22件一致（日本語11件、英語11件。問題の英語例は3回ともnudge_left）。
質問／相談、丁寧な移動依頼、言い直し、現在操作あり／なし、未観測の目的地、発話停止と身体STOPを含む。
API解釈時間は982〜2296ms。これは音声認識やBrain／身体の遅延を含まない。
限られた例文の分類試験であり、任意の音声発話の成功率ではない。
API到達前のsandbox DNS失敗は分類試験の母数に含めない。

Live向け観測更新は、sequenceだけの更新で再注入しないこと、変化／失効をthinkingだけで通知すること、
失効factsを残さないことをwatchdogのオフライン検査で確認した。

未実施：今回の変更を通したGPT Live実マイク／音声、Windows実Brain＋Unityでの移動、
センサー→音声計画の実機往復、NEAR閾値・余動、Brain適用待ちを含む操作感。
producerはソース上で接続済みだが、起動中のアプリへ反映したことは確認していない。
新鮮なsnapshotが届けば計画開始を許可し、欠損なら引き続き拒否する。
台本用blind_run_cueは部分的な観測なので、安全snapshotとして流用しない。
モデルが全ての曖昧な発話を正しく解釈する保証はない。
サーバー再起動、Unity起動、commit/pushは今回行わない。Responses分類だけを実APIで検証する。
