# 質問後の接続継続検証

2026-09-14。正本設計は [Brain・GPT Live共通設計](../Brain-GPTLive-CrossPlatform-Design.md)。この文書は今回の実測結果であり、連続無障害の完成証明ではない。

## 結果

`question-connection-ja` と `question-connection-en` は双方 **connection_stability_failed**。既知の `invalid_context_channel` 回帰は今回の確定ログから消失し、質問後の再移動は成功した。しかし各試行で制御喪失1回、観測中のepoch変化3回があり、最終 `LastAppliedAction == STOP` の判定は双方falseだった。終了コード0や最後のfresh復帰を成功へ読み替えない。

Windows Player → 同居Bridge → 実Windows Brain（127.0.0.1:18766、MALECNS_EXPERIMENTAL）→神経出力→motor→Unityの経路。実GPT-Liveへ明示された合成テキストを送信した試験で、マイク入力の検証ではない。Brain readyは受信値のfalseを維持した。

| 項目 | 日本語 | 英語 |
|---|---:|---:|
| 結果 | failed | failed |
| movedAfterQuestion | true | true |
| 質問後変位 m | 1.028684 | 0.635089 |
| controlLossEpisodes / controlEpochChanges | 1 / 3 | 1 / 3 |
| stopped / 最終fresh | false / true | false / false |
| Player firstSequence / lastSequence | 31 / 293 | 12 / -1 |
| Player frames / neuralFrames | 285 / 282 | 272 / 269 |
| Unity frame p95 ms | 16.6993 | 16.7024 |
| 保存Bridge frame母数・seq範囲 | 296、3–298 | 278、3–280 |
| Brain step p95 / max ms | 231.254 / 1065.153 | 232.903 / 1082.718 |
| Player sampled peak RSS bytes | 592842752 | 595095552 |
| 喪失後STOP request11 送信→適用 ms | 2156 | 1203 |

Brain stepは全保存ローテーションの `frame.performance.stepWallTimeMs`、p95は親の全保存frame集計（昇順配列の index=floor((n−1)×0.95)、補間なし）。Player frame母数と異なる。RSSは5秒間隔サンプリングで真の瞬間最大値ではない。保存されたprocess treeにBrain本体の大容量RSSを確実に同定できる情報はなく、上表をBrain RSSや全process合計と呼ばない。英語の末尾seq=-1は切断状態の値で、Brainが負のsequenceを生成した意味ではない。

## 旧回帰と今回の遅延は別原因

旧 `visual-commentary-ja-short` はmonotonic 176011125ms、旧英語は176092171msに `intent_rejected(reason=invalid_context_channel)`（epoch3）→ `output_inhibited(reason=intent_service_failed)`（epoch4）。receipt実装時のチャネル許可リストが既存 `instructions` を除外し、質問の `speak_non_action` が例外を出した。Bridgeのinhibit処理がmotor TCPを閉じ、Playerで最後のseq229／233に切断が見えた。自然発生のTCP障害ではなかった。

修正は `instructions` 許可の復元、未知チャネル拒否の維持、instructions ACKの相関。純粋回帰試験は実Bridgeと実ConversationAdapterを使い、外部WebSocket送信だけを代替して日英のthinking→instructions順、target_changed、trace、未知チャネル拒否を検査する。Brainモックで移動を代替した試験ではない。親の統合検証は42 tests PASS、1.288秒。

今回の両ログに `invalid_context_channel` はない。一方、Brainの50ms窓計算のwall時間が750ms stale閾値を超えた。

- 日本語：seq289受信179377718ms→seq290受信179378500ms（782ms間隔）。seq290のstep755.237ms、seq291は1061.876ms、seq292は1065.153ms。Playerはseq289でserverAge754.8msを記録。179378484msのmotor_client_disconnectedが最初のBridge抑止。
- 英語：seq273のstep875.858ms、seq274は1082.718ms、seq275は1069.187ms。最初のmotor_client_disconnectedは179520828ms。

計算窓の遅延は実測されているが、その内訳（数値状態、CPUスケジューリング、他process負荷など）は未確定。subnormalは仮説であり原因と断定しない。固定750ms閾値は緩和していない。

## STOPの送信と身体停止を区別

日本語は喪失後のsafety STOP request10と11を179378484msに送信。request11は179378515msにACK、179380640msのseq292で適用（2156ms）。request10は後続に置き換わった。英語はrequest11を179520843msに送信・ACK、179522046msのseq274で適用（1203ms）。これは神経側Action適用の観測で、身体が停止した証明ではない。両Playerの `stopped=false` を保持する。終了処理の追加STOP／epoch増加を、Probe観測中の3変化へ混ぜない。

## ビルドと残るgate

Unity compile成功。Player buildは12:37:40→12:38:01 UTCにSucceeded。CLIの5秒応答待ちtimeout1回はビルド結果と分離する。これらは親による確認記録であり、実Playerのfailedを取り消さない。

次はBrainの数値・刺激・decoder・stale閾値を変えずに遅延を診断する。窓計算時間、frame生成／Bridge受信／Unity受信の時刻、CPU負荷・RSSを分けて記録し、長時間Playerで質問→再移動→STOPと制御喪失の有無を確認する。今回は無障害連続プレイを達成していない。

## 証拠

- `artifacts/neural-feedback/question-connection-{ja,en}.json`：Player判定。
- 同prefixの `-bridge.jsonl`、`.1`、`.2`：全保存frame、Action、抑止の時系列。
- 同prefixの `-player.log`：NATIVE_BODY_STOP。
- 同prefixの `-metrics.json`：5秒RSSサンプリング。
- 旧 `visual-commentary-{ja,en}-short-bridge.jsonl*`：チャネル回帰の確定記録。

source hashの保存先は `artifacts/neural-feedback/question-connection-source-hashes.json`。Brain入力・graph・motor設定・依存版は [前段の実測](Visual-Threat-Game-Integration.md) と同じ。神経モデル・decoder・physics・設定定義の変更はない。

実行コマンド：

```powershell
& tools/neural_player_trial.ps1 -Name question-connection-ja -Language ja -Question 0 -ConnectionStability
& tools/neural_player_trial.ps1 -Name question-connection-en -Language en -Question 0 -ConnectionStability
```

保存Bridge frameの先頭から末尾までの観測時間は日本語47.610秒、英語45.750秒。これはPlayer起動全体の所要時間とは異なる。

## 後続修正

極小値の減衰に対する数値不変の最適化と、STOP後の監視を延長した再検証は [過渡subnormalの遅延対策](Transient-Subnormal-Latency.md) を参照。上記の旧failed記録は保持する。
