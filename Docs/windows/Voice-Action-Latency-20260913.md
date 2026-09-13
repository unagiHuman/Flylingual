# 音声から身体への応答短縮・検証記録

2026-09-13。通常の `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` を再ビルドした。明確な短文の追加LLM待ち、delegation到着による再分類・取りこぼし、一律1秒の本文待ちを改善した。純粋旋回は前方障害だけで拒否しない。あいまいな言葉の既存解釈、距離・時間・継続の意味は保持する。[実装仕様](../integration/Voice-Action-Latency.md)参照。

## 実際の音声・Brain・身体の結果

Windows内の通常Playerから合成PCMを実GPT Liveへ送った。認識本文からBridge、実Windows Brain `127.0.0.1:18766`、神経出力、既存decoder、CPG/PhysXを通すLIVE試験であり、Actionやmotorの注入、Replayによる代替はない。backendは `MALECNS_EXPERIMENTAL`、受信した `ready=false` を維持。今回の実マイク試験は行っていない。

各1回の測定。時間の基点は**合成音声ファイルの送信終端**であり、ファイル末尾の無音も含む。実際の発話終端と混同しない。

| 実認識本文 | 解釈経路 | ファイル送信終端→Brain適用 | ファイル送信終端→身体動作開始 | 結果 |
|---|---|---:|---:|---|
| 8秒間前に進んで | rules | 0.764秒 | 1.010秒 | PASS、実移動 |
| とどまって | rules | 0.754秒 | 対象外 | PASS、STOP適用と停止 |
| 8秒間右に曲がって | rules | 0.805秒 | 1.528秒 | PASS、実旋回 |
| ちょっと前に進んだ | model | 4.224秒 | 4.448秒 | 実移動、TTL停止確認項目は未完了 |

明確な3件の本文候補の受付からBrain適用までは0.313 / 0.328 / 0.375秒。規則経路は追加LLMを呼ばず、解釈時間は診断のミリ秒分解能で0msだった。4件目は閉じた規則の対象外で、既存モデルが0.5m前進と解釈し、解釈に3.359秒かかった。あいまいな指示のモデル待ちは残っている。

音声エネルギーから推定した有声音声終端を基点にすると、身体動作開始は前進約1.66秒、右旋回約2.23秒。これはBridge時計とUnityの受信時計を対応させた近似であり、物理マイクの精密計測ではない。末尾無音を含む上表とは別指標として[集計原本](../../artifacts/voice-latency/after-01/latency-summary.json)に保持する。身体開始は適用後の新規BrainFrame、motor、CPG位相、接地、微小な実変位またはyaw変化で検出し、移動完了とは区別する。

4件目は実際に約1.15m移動し、`distance_overshoot` で実行終了した。旧smoke probeが距離終了に対して `command_expired` を待つため、結果全体は `incomplete / ttl_stop_not_confirmed`。この失敗をPASSに書き換えない。短距離の過走は[前回の距離検証](Distance-Intent-Validation-20260913.md)でも確認済みで、今回の応答短縮で停止位置の追込みは追加しない。

変更前 `before-01` は最初の音声認識「8秒間前に進む」後にAction適用へ進まず、`voice_apply_timeout` で未完了だった。同一条件で成功した変更前のレイテンシがないため、何%高速化したという比較は行わない。

## 再現条件と証拠

リポジトリルートから実行したコマンド（beforeはoutputだけbefore-01）：

```powershell
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v2/manifest.json --suite smoke --seconds 100 --capture-test-transcript --output artifacts/voice-latency/after-01
```

- [Player結果](../../artifacts/voice-latency/after-01/report.json)、[音声・制御イベント](../../artifacts/voice-latency/after-01/events.jsonl)、[身体観測](../../artifacts/voice-latency/after-01/observations.jsonl)。4件ともfreshMaintained、sameEpoch、sameSessionを維持。
- [source/data/config/fixture hash・依存版・所有プロセス記録](../../artifacts/voice-latency/after-01/runner-metadata.json)。wall 52.703秒、peak process-tree RSS 1,157,324,800 bytes、Player例外0、残留所有PIDなし、使用port解放済み。Player内の終了通知未確認とは別に、runnerでプロセス終了を確認した。
- [Bridge集計](../../artifacts/voice-latency/after-01/brain-evidence.json)：制御イベントの時計区間内でBrainFrame 194件、sequence 5→198、最大受信間隔313ms。Brain窓計算中央値152.998ms、最大289.883ms。command applied E2Eは中央値328ms、最大547ms（STOPを含む）。同区間にstale/transport理由のinhibitなし。起動時の `native_voice_control` 抑止は別途記録されている。
- [変更前原本](../../artifacts/voice-latency/before-01/runner-metadata.json)。前後とも実API・Windows Brainで試験し、未完了の理由を分けて保存した。

Unity CLIから停止中EditorへRefresh/コンパイルを要求し、`scriptCompilationFailed=false` を確認して通常Playerをビルドした。神経モデル、重み、decoder、物理設定の変更はない。プロトコル・解釈・実行のオフラインテスト189件もPASS（89件5.665秒、99件4.331秒、雑音時の無期限待ち防止1件0.148秒）。これは実API・身体試験とは別の証拠である。

未確認は今回の実マイク操作感、幅広い雑音・言い直し条件での発話境界、モデル経路の応答時間の分布。旋回を実yawの目標角度で完了させる変更は今回実装していない。既存の実行中指示の更新・距離制御を保持し、入力不能に関係しない精密停止試験は追加しなかった。commit/pushは行っていない。
