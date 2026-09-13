# 停滞時のハエたたき

正式シーンの `Blind Sugar Run Game Session` にある `BlindSugarRunIdleSwatter` で調整する。

| Inspector項目 | 初期値 | 意味 |
|---|---:|---|
| Idle Seconds | 20秒 | 予告を含む、停滞から打撃までの時間 |
| Warning Seconds | 4秒 | 打撃前の回避可能な予告時間 |
| Movement Threshold | 0.3 | 水平面で基準位置からこの距離を動くと計測をリセット |

実身体操作が一度有効になってから計測する。通常のSTOPや意図的な静止も対象。脚の動き・回転・細かな位置揺れの累積距離ではリセットせず、身体のXZ変位で判断する。

予告中は赤い格子状のハエたたき、警告音、残り秒数を表示し、LiveGPTへ「ハエたたきが来る！ 動かなきゃ」の根拠付き台本通知を送る。移動による回避で表示・待機中通知を解除する。既にAPIへ送信した音声は撤回できない。

20秒に達すると打撃音・降下演出からGameOverへ移り、既存のRetryで開始地点へ戻れる。判定にGPTの返答を待たない。演出にColliderやmotor上書きはなく、既存のBrain／PhysX経路を保持する。

ポーズ・接続待ちでは経過時間を保持して計測を休止する。Goal／Reveal／RetryなどPlaying以外では解除する。崖の接近だけでは停止せず、従来の落下GameOverも維持する。

## 検証（2026-09-13）

- Unity Editor、Windows実Brain `127.0.0.1:18766`、`MALECNS_EXPERIMENTAL`、raw ready=false。通常テキスト入力を使用。
- 約16秒で予告、20.0036秒でGameOver。専用メッセージとRetryを確認。
- Retry後、予告中の通常「前に進んで」で身体が約0.41移動し、経過時間が0.103秒へ戻って回避。続けて通常STOPを適用。
- Editorポーズ中は経過時間17.98752秒で一定。再開時の接続復帰待ちも計測せず、復帰後20.00343秒でGameOver。sequence184→235。
- 台本検証9件合格。実接続で台本通知のqueued ACKを確認。今回の音声の聴取確認は未実施。
- 最終の独立予告パネルを目視確認し、LiveGPTの「ハエたたきが来る。動かなきゃ」の字幕も確認。描画確認だけは実行中の待ち時間を120秒へ延長したため、`warning-visible.png`の残り秒数は検証用。保存シーンは20秒／予告4秒のまま。
- Goal／Reveal中の抑止はコード確認。橋での宙づりそのものの再現試行は今回行わず、共通の停滞判定を実身体で検証した。

証拠は `artifacts/swatter-20260913/` のCSV、通知JSONL、画像。ゲームコードのコンパイルはPipelineでエラーなし。旧safe-compile補助スクリプトはこのprojectに未導入のuloopを要求したため、導入済みUnity Pipelineで確認した。

正式Windows Playerは2026-09-13 23:33 JSTに更新。BuildReportはSucceeded、28.32秒、warning36、error1。この1件はビルド中のPipeline要求の5秒タイムアウトであり、コンパイルエラーではない。`build-report.json`に原文を保存。動作検証はEditorで実施し、更新後Player自体の再プレイは未実施。EditorはEdit Modeで終了した。
