# 音声指示の鮮度と実行時間の分離

2026-09-13。ユーザーの通常マイク実行で、FORWARDが認識されても動かなかった問題を修正した。

## 原因と変更

直前の実行では `validForMs=4000` に対して解釈時間が4766msあり、従来の `4000 - 4766` により `invalid_command_duration` で拒否された。保存された322 BrainFrame（sequence 231〜552）はすべてSTOP、motor=0だった。[診断原本](../../artifacts/voice-tests/user-mic-20260913-141626-diagnosis.json)。

- `control.maxIntentAgeMs` を独立設定として追加。既定8000ms、正の有限値かつ8000ms以下。解釈開始からこの値未満の指示だけを受け付け、取消待ち後にも再検査する。
- 受け付けたActionは、その時点から `validForMs` の動作時間を持つ。解釈時間を差し引かない。動作時間の既定4000ms・最大8000msを維持する。
- Planも、古いPlanの取消と鮮度/安全確認が終わった受付時点から、全step共通の実行期限を開始する。step移行で期限を延長しない。
- STOPは引き続き動作期限を持たない。旧epoch/revision、stale Brain、接続断、危険・安全観測不足による拒否は維持する。
- `command_submitted` に `intentAgeMs` と `executionDurationMs` を記録し、待ち時間と動作時間を区別する。

受付時点はBrainへの提出直前であり、Brain適用や物理的な始動が即時になるという保証ではない。GPT Liveが指示を委譲しない問題、解釈自体が8秒以上かかるケース、PlanへのUnity安全情報の未接続は別の原因として残る。

## 検証

オフライン65テストが合格。実障害の4.766秒解釈後にAction/Planが満額4秒を確保すること、7.999秒と8秒の境界、取消待ち中の期限/世代変更、STOP、既存TTL停止、Plan安全観測の拒否を確認した。従来の「4.5秒の解釈後にFORWARDを拒否する」テストは、満額の動作を期待する回帰へ修正した。

Unity 6000.5.9f1でコンパイルと正式Playerビルドが成功。Brainの計算・motor・物理リグ・モデルは変更していない。

時間指定なしの「前に進んで」「右に曲がって」「左に曲がって」を追加した `duration` suiteで、音声→実Brain適用→適用後の身体→実行期間→期限切れSTOP→静止を順に確認する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/generate_voice_fixtures.ps1 -OutputDir artifacts/voice-fixtures/haruka-ja-v2
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v2/manifest.json --suite duration --output artifacts/voice-tests/duration-01
```

実行期間は同じBridgeの単調時計で提出から期限切れまでを測定し、指定時間との差が早期50ms・遅延750ms以内であることを確認する。音声の期待値をGPTへ文字列として渡さず、固定motor・テキスト指示で代用しない。実マイク機器の再試験とは区別する。

## 実サービス結果

`duration-01` は実Windows Brain `127.0.0.1:18766`、LIVE / MALECNS_EXPERIMENTAL / ready=false、GPT Live / Responsesを使用。

| 通常の音声指示 | 解釈時間 | 受理した動作時間 | 提出→期限切れ | 実身体 |
| --- | --- | --- | --- | --- |
| 前に進んで | 1969ms | 4000ms | 4000ms | 前進と停止を確認 |
| 右に曲がって | 1547ms | 4000ms | 4063ms | 右旋回と停止を確認 |
| 左に曲がって | 分類・適用未観測 | 未受理 | 該当なし | `voice_apply_timeout` |

前進と右旋回は音声相関、原本requestId/sequence、適用後の身体運動、満額の動作時間、TTL停止後の静止に合格。同じepoch/sessionとfresh frameを維持した。前進は音声先頭から適用まで4.525秒、右旋回4.148秒。

3件目は25秒以内に音声に対応する指示適用を観測できず、全suiteは `incomplete` とした。今回修正した動作時間の減算による拒否とは別であり、連続音声指示の完全な受入れ成功を主張しない。解釈4.766秒の厳密再現はオフライン回帰であり、今回の実API応答を人工的に遅らせてはいない。

原本: `artifacts/voice-tests/duration-01/report.json`、`events.jsonl`、`observations.jsonl`、`runner-metadata.json`。runner wall=53.656秒、peak process-tree RSS=1,165,279,232 bytes、Player例外0、exit=0、owned PID=[]、終了後3port解放。source/config/data/Player/fixture hashと依存版はmetadataに保存。
