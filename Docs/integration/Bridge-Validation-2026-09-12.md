# Bridge bidirectional integration checkpoint — 2026-09-12

`ready=false`。実MaleCNS＋会話MOCKで双方向の経路を検証した。GPT-Live実API、マイク／スピーカー、Windows Unityは未検証。旧checkpointの科学的妥当性をこの試験で再認定しない。

## 実行条件

- Repository: Flylingual/main。Brainの8ファイルaggregate source SHA: `3755ee05a6d6e9b622f0ec7522fb8d73bbb77303be4217ef67dbdda4182d8fd7`。
- Config SHA: `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。
- Graph 4 NPY aggregate SHA: `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`。個別SHAは `Brain/MaleCNS/config/analog_handoff_manifest.json` とdoctorで照合済み。
- Python 3.10、aiohttp 3.14.3、Brain NumPy 1.24.3。Brain Pythonは既存flybrain-malecns環境、Bridgeは別venv。Mac上の実行。
- seed `20270101`、window 50 ms、dt 0.1 ms。通常のpersistent controller。production weight／threshold／NT／calibrationは変更なし。作業開始時の基準commitは `0cc83be`。Bridge実装は本記録を追加したcommitに対応する。
- 自己所有Brain `127.0.0.1:18767`、Bridge TCP `18770`、HTTP/WS `18771`。既存8766／旧サーバーへの接続・停止は行っていない。

起動コマンド:

```sh
.venv-bridge/bin/python tools/dev.py up --profile mac-local --local artifacts/bridge-validation/local.json --conversation mock --launch-brain
```

ローカル設定は上記3 port、当該端末のBrain Python、`logPath=artifacts/bridge-validation/events.jsonl`。検証クライアントは一時的なinline asyncio/aiohttpによるWS/TCP観測で、新しいテストコードファイルは追加していない。raw出力はGit外 `artifacts/bridge-validation/` に保持。

## 実Brainの6 Action

単一persistent network、1 seedの統合試験。各刺激2.7秒wall＋STOP 2.7秒wall。値は各刺激の末尾3 frame平均（STOPは開始時の1 frame）。元の独立5-seedの校正試験とは別。

| Action | 刺激中frame数 | forward | turn | 期待符号 |
| --- | ---: | ---: | ---: | --- |
| STOP | 1 | 0 | 0 | pass |
| FORWARD | 11 | 0.8168 | 0 | pass |
| TURN_R | 11 | 0 | +0.6620 | pass |
| TURN_L | 12 | 0 | -0.9275 | pass |
| FORWARD_R | 12 | 0.9030 | +0.9630 | pass |
| FORWARD_L | 11 | 0.9551 | -0.8249 | pass |

合計170 frameを観測。日本語の入力はmock辞書でAction提案に変換し、実MaleCNSの神経経路を通した。Actionからmotor値を合成していない。観測状態への質問は決定的な要約へ戻り、unsupportedな「飛んで」は確認要求となり刺激を送らない。

## 制御・transport

- 二つ目の制御WSをHTTP409で拒否。旧epoch・重複commandId・manual/GPT競合を拒否。
- GPT操作が4秒で期限切れ→STOP要求＋抑止。緊急停止は明示resumeまでラッチ。
- 自己所有Brainを1.2秒だけSIGSTOPし必ずSIGCONT。frame age 1307 msの観測時に `stale_brain` 抑止を確認（判定閾値は750 msのまま）。
- Unity互換TCP requestId `77` と上流requestId `33` の写像。sequence `1352` の両transport到着を待って `motor`／`raw`／`brain` の完全一致。最初の比較はWS到着前に行ってfalseになったため、同一sequence待機へ診断を修正して再確認した。
- TCP client切断で抑止。manual中の会話停止は操作権を奪わず、gpt中の会話停止はSTOP＋抑止。
- `windows-local → mac-local` のprofile往復で異なるsession 3個、旧controller解放証跡、明示resumeを確認。ただしlocal.jsonで全profileを**同一Macの同一endpoint**へ上書きしたlifecycle試験であり、跨OSの接続先切替ではない。
- HTTP/WSの異originを403で拒否。Brain/backend/data/config/sourceの期待hash一致、reader解放を確認。切替が失敗した場合の実Windows挙動は未検証。
- 最終の短時間起動・質問試験でも `activeControllerCount=0` のreleaseログとlauncher正常終了を確認。検証後の専用Brain/Bridgeは停止した。

## 性能（新しいMac統合試験）

| 計測 | 母数 | mean | median | p95 |
| --- | ---: | ---: | ---: | ---: |
| 50 ms Brain step wall | 170 | 218.22 ms | 217.17 ms | 225.58 ms |
| Bridge送信→applied frame受信 | 16 | 319.20 ms | 320.77 ms | 431.78 ms |

p95は昇順配列の `floor(0.95*N)` 番目（0-based、上端clamp）。E2EはBridge内の単調時計のみ。音声推論時間／Unity描画／身体動作の時間を含まない。

別の最終起動ではプロセス生成→Brain READYが799.70 ms。import・graph hash・初期化込みで、純粋なinitialize時間ではない。launcher familyのOS rusage peak RSSは261.69 MiB。長時間試験後の単一時点RSSはBrain 60.80 MiB、Bridge 32.47 MiB（mmap/OS常駐ページを含む状態依存値であり、各プロセスpeakではない）。リアルタイム性能認定はしない。

## APIと残りgate

APIイベント契約は公式の[Voice WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets)、[client delegation](https://developers.openai.com/api/docs/guides/live-delegation)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)を基準に実装。実APIは一度も呼んでいない。キー設定の存在だけ確認し、値は取得・出力していない。

18件のoffline検査では、無効Action、旧epoch、重複、TTLの負数／巨大整数／NaN／infinity／bool／上限超過、非所有者、stale上限と不明要約、LAN禁止、user transcriptのみのdelegation、旧transcript破棄、structured output、session start/closeなどを確認した。mock/stub検査はモデルの実応答・発話意図の精度・音声品質を証明しない。

次に必要なのは、Bridgeホストの `OPENAI_API_KEY` とモデル利用権限、実GPT-Liveの文字／音声往復、実マイクでのecho抑止、Windows AudioAdapter／独立出力抑止、Windows Brain↔Mac Brainの往復とUnity gameplay受入れ。API／Windows gateが通るまでreadyを昇格しない。

## ローカル証跡

- `integration_result.json` / `frames.jsonl` / `client_events.json`: 6 Actionとprofile往復。
- `offline_result.json`: 非課金の契約／制御検査。
- `final_offline_hardening.json`: 音声送信queueとcleanup、旧音声epoch拒否、consumer例外のfail-closedを追加で4件確認。
- `transport_result.json` / `wire_mapping_result.json`: stale、owner、TCP/WS比較。
- `process_snapshot.json` / `final_start_stop_result.json`: RSS、最終startup/release。
- `events.jsonl`: 原本BrainFrame、sequence、上流ID、commandId、epoch、accepted/applied、stale、解放。

上記はすべて `artifacts/bridge-validation/`。会話MOCKの診断本文を含む一時client結果はGit外。通常runtimeの本文／音声保存は無効。
