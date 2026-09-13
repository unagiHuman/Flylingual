# blind_run_script_v1

2026-09-13。Backend受信実装あり、Unityのセンサー／GameFlow producer未接続。
既存 `/ws` の単一control clientだけが送信する。別controllerやBrain TCPへ送らない。
`bridge_state.capabilities` の `blind_run_script_v1` を確認して利用する。

## blind_run_cue

必須キーは以下の9個のみ（未知キー拒否）。

```json
{
  "type": "blind_run_cue",
  "controlEpoch": 1,
  "conversationGeneration": 1,
  "runId": "local-run-1",
  "attempt": 1,
  "sequence": 1,
  "ageMs": 0,
  "cue": "intro",
  "evidence": {"stageStarted": true}
}
```

`runId`は1〜64文字、attemptは1〜10000の整数、sequenceは1〜2^53の整数で会話内で単調増加。
ageMsは観測から送信までの経過ms、有限の0〜750。異なるPCの時計を減算しない。
Unityは送信直前にageを更新し、滞留した通知を破棄する。Bridgeは輸送遅延を独立に証明しない。
epochとconversationGenerationは最新stateと一致し、liveかつcontrol interactionが必要。
chat_only、切替中、release unknown、Brain stale（link_error以外）では拒否。

`cue`と`evidence`の正本は[台本JSON](../../Runtime/Bridge/blind_run_script.json)。
各cueはevidenceが型も含めて完全一致する場合だけ受理する。任意文章、座標、地図、経路の添付は禁止。
Unityは実センサー・GameFlowから値を作る。Bridge側の型検査はUnityの観測が真実であることの証明ではない。
rootのGoal安定時間、Reveal開始、局所検出範囲の妥当性はUnity側で実測する。

初回はintro＋attempt=1。同じ会話では同じrunIdを維持。New Gameは会話を安全に終了し新規開始する。
再接続時も旧cueを再送しない。会話停止／開始で台本状態と落下記憶を破棄する。

### fall / retry

fallのevidenceは以下のみ。technicalFault=falseのゲーム落下だけを記憶する。

```json
{"ground":"ruler","lastAction":"TURN_R","leftEdge":"safe","rightEdge":"very_near","technicalFault":false}
```

groundはunknown/desk/ruler/book/plate、lastActionは既存6 Action、左右edgeはunknown/safe/near/very_near。
lastActionはUnityが落下直前に観測したActionを使用し、台本処理はそれを実行しない。
fall後はretryまたはlink_error以外を拒否。
retryは空evidence、attemptを1増やす。前回の端観測を一度だけ述べて記憶を破棄する。
障害に伴う落下ではfallを送らずlink_errorを送る。障害時に身体が落ちてもゲーム失敗へ変換しない。

goalはinsideGoal/bodyStable/goalConfirmed=trueが必要。
revealは先にgoalを受理し、UnityがrevealStarted=trueを通知してから。
台本のセリフ、字幕やAPI応答でGoal／Revealを起動してはならない。

## 発話・応答

intro/vision/ask/各lesson/retry/goal/revealはattemptごとに一度だけ。
通常観測は同じcueを繰り返さず、別cueでも原則3秒間隔。urgent/fall/link_errorは間隔の例外。
抑制中も最新行を背景情報へ渡す。これは完全な無発話保証ではなく、GPT Liveが後で利用可能な情報。
会話本体も原則ひと言。全cue一覧やrunId、cue名はGPTへ送らない。

応答：`{"type":"blind_run_cue_result","sequence":1,"stage":"queued","speakRequested":true}`。
queuedはappend送信までで、API受領ACK、発話完了、再生完了、プレイ成功を意味しない。
ログ `blind_run_cue_queued` はcue/sequence/speakRequestedのみ。本文・PCM・evidenceは新規保存しない。
不正入力は既存error経路。既存BrainFrame、6 Action、期限・排他・stale・STOP処理は変更しない。
