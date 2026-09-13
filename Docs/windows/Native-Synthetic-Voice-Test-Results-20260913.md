# 音声自動テストの実測（2026-09-13）

## 実装と条件

日本語合成音声をUnityの共通PCM送信経路へ注入する機構を実装した。[実行手順](Native-Synthetic-Voice-Tests.md)。実マイク・スピーカーの音響経路は未検証。

Windows 11、Unity 6000.5.9f1、正式BlindSugarRunPlayシーンのDevelopment Player。実Windows Brain `127.0.0.1:18766`、同居Bridge motor/control `18770/18771`。`LIVE / MALECNS_EXPERIMENTAL / ready=false`、gpt-live-1とgpt-5.6-lunaを使用。Brainの数値・TTL・motor・モデルを試験のために変更していない。

Microsoft Haruka Desktop / rate=0 / PCM16 mono 24kHz、11音声をローカル生成。固定manifestとWAVは `artifacts/voice-fixtures/haruka-ja-v1/`。台本と期待値をモデルへ文字列送信していない。

## 初回の実サービス検証

```powershell
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v1/manifest.json --suite smoke --output artifacts/voice-tests/smoke-01
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v1/manifest.json --suite plans --output artifacts/voice-tests/plans-01
```

| 試験 | 母数と観測 | 結果 |
| --- | --- | --- |
| smoke-01 前進 | 音声先頭→Brain適用6.407秒、身体始動6.640秒。requestId=3 / sequence=82 | 音声相関・前進を確認 |
| smoke-01 STOP | 音声先頭→Brain適用8.271秒。音声STOP requestId=5 / sequence=134 | 時間切れSTOP（requestId=4 / sequence=118）が先行したため `incomplete` |
| plans-01 | 「ちょっと右」→nudge_right、「右側に進んで」→right_then_forward、「違和感があったら止まれ」→forward_until_concern。3/3で音声相関とPlan名が一致 | 全件 `local_observation_unavailable` により `blocked`。Plan身体操作の成功ではない |

STOPの時系列はUnityローカル時刻で、前進適用16.830秒、TTL期限切れ22.174秒、時間切れSTOP適用22.594秒、音声STOP適用25.401秒。音声STOPの分類・適用自体は成功したが、先行する時間切れを音声停止の成果として扱わない。

両runのcase中はepoch=3、conversationGeneration=2、同じBrain session/instance、live motor sourceを維持。観測ログは初期のsequence=0（frame欠測）もそのまま保存している。caseの最大frame ageはsmokeの前進0.196秒・STOP0.256秒で、0.75秒のstale閾値内。plansは身体が動いたとは判定していない。

| run | runner wall | peak process-tree RSS | Player例外 | 終了 |
| --- | --- | --- | --- | --- |
| smoke-01 | 57.234秒 | 1,175,724,032 bytes | 0 | exit=0、owned PID=[]、3port解放 |
| plans-01 | 25.157秒 | 1,139,310,592 bytes | 0 | exit=0、owned PID=[]、3port解放 |

各runの `report.json`、`events.jsonl`、`observations.jsonl`、`runner-metadata.json` を原本とする。source/config/data/Player/fixture hashは各metadataを参照。初回runnerはhashを終了時に採取しており、最新版は起動前に固定する。初回の `lastAudioAt` は最後の100ms chunkの送出開始であり、厳密な音声終端ではない。遅延表は音声先頭からの値を使用した。

## 追加確認と残るgate

Pythonの診断・継続制御・runner検証39件、UnityのWAV変換/破損/長さ制限4件が合格。実サービスの成功とは区別する。

初回後、fixture周期を絶対予定時刻基準へ修正し、適用後の原本requestId/sequenceと身体集計を照合する判定、対象STOPのsequence照合、終了未確認時の合格取消を追加した。

最新版 `smoke-02` では前進の原本requestId=3 / sequence=111と同じ実TCP frameを照合し、その後の身体前進5.91mm・CPG位相変化1.81radを確認。音声先頭→適用9.508秒、身体始動9.727秒。送信間隔は97.10〜104.96msで、フレーム遅れの累積を抑制できた。

続くSTOPは全16chunkを送ったが、20秒の適用待ち内にSTOPに対応するdelegation/command適用を観測できず `voice_apply_timeout` となった。前進のTTL停止は発生している。これは初回の「遅れてSTOP適用」と区別して記録する。再現のためにTTL延長・テキスト指示・motor直接操作は行っていない。

`smoke-02` のrunner wall=39.094秒、peak process-tree RSS=1,135,665,152 bytes、Player例外0、exit=0、owned PID=[]、port解放。原本は `artifacts/voice-tests/smoke-02/`。Python 3.10.12、aiohttp 3.14.3、psutil 7.2.2、Brain側numpy 1.24.3 / numba 0.61.2 / llvmlite 0.44.0を記録。

最新版 `plans-02` でも3/3で期待Planと音声相関が一致し、3件とも `local_observation_unavailable` による `blocked` を再確認した。runner wall=23.844秒、peak process-tree RSS=1,145,896,960 bytes、Player例外0、exit=0、owned PID=[]、port解放。原本は `artifacts/voice-tests/plans-02/`。最新2runのsource/config/data/Player/fixture hashに欠測はない。

音声停止が時間内に適用されること、Planへ実センサー観測が届くことが残る。初回smokeが停止で中断したため、その実測から返信中指示・待受3巡・6動作各3回・長時間安定性の合格を主張しない。物理マイクを含む機器試験も別gate。
