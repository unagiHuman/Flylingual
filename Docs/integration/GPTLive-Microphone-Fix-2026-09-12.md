# GPT Live マイク応答修正検証

実施日: 2026-09-12。対象は Mac ローカル Bridge の browser player 音声経路であり、
Windows Unity・実身体の受入れではない。入力証拠は
`artifacts/bridge-validation/voice_no_response_before.json` と
`artifacts/bridge-validation/voice_no_response_after.json`、実装確認対象は
`Runtime/Player/audio.js`、`Runtime/Bridge/conversation.py`、
`Runtime/Bridge/server.py` である。音声・会話本文・APIキーは保存または本書へ転載しない。

## 原因

修正前は出力音声の strict-zero 区間まで playback 全体として扱い、echo 抑止の終端が延長され続けていた。その結果、入力送信が停止した。

- 修正前の入力: 5 chunks、最終送信から 33.9 秒、入力 -34.7 dBFS
- 出力: zero 377 / nonzero 118 chunks
- queue high-water: 1、backpressure: 0

これは stale safety stop の後に発生した別の `live_stream_failed` 表示とは分離して判定する。closing 後の既知エラーを通常の失敗として記録しない抑止も実装確認した。

## 修正と確認結果

再生の `nextTime` を保持し、strict-zero 区間では playback timeline を進めるだけにした。有音区間と末尾 200 ms のみ echo 抑止対象とし、音声キューを順序再生する。

実 speaker → 実 mic → Chrome の音響経路で、入力は人間の肉声ではなく macOS `say` による既知フレーズである。

- 修正後の先行送信: 263 chunks
- 既知フレーズ: input transcript 11 deltas、21文字、合言葉の認識と要求フレーズを含む返答を確認
- 返答後の再入力: 16 deltas。マイク再開を確認
- 最終診断: input 1473 / sent 1465、output zero 1420 / nonzero 150、error 0
- queue depth 0、high-water 11、backpressure 0
- pure-audio checks: zeroでtimeline維持、有音区間抑止、200 ms tail、zero tail後の再入力、stop時node破棄、安全ゲートを確認

二度目の STOP 相当フレーズは認識されたが、accepted client delegation および GPT-origin STOP submit は観測されず、Brain Action 適用とは扱わない。最終 `delegationCount` は 0 である。

## 実行条件と境界

- Python 3.10.21、aiohttp 3.14.3
- Bridge HTTP/WS: localhost:18771、Brain: localhost:18767
- Chrome は外部Chromeの新規検証。08:37 UTC以降の新規 error/warn は 0
- 08:27 UTC の旧 video error 1件は別試験であり、本検証の結果に含めない
- 750 ms stale safety、LIF、weights、`ready` は変更していない
- Windows、Unity、実マイクの人間音声、実身体、跨OS接続は未実施
- APIキー、PCM、会話本文は本書に含めない

本書は [Bridge v1 protocol](../../Contracts/bridge-v1/protocol.md) の任意
`audioDiagnostics` 契約を参照する。diagnostics は入力・音声 transport の観測であり、
ASRの正しさ、Brain適用、神経応答、実身体動作の証明ではない。実Brain／実API／Windows Unity の各gateは独立して判定する。
