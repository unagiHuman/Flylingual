# Live Browser/API 検証記録

実施日: 2026-09-12。Mac の限定実測。設計上の正本は [Brain・GPT Live の共通設計ルール](../Brain-GPTLive-CrossPlatform-Design.md)、MOCK の履歴は [Bridge 検証記録](Bridge-Validation-2026-09-12.md) に残す。本記録はその MOCK 合格を live、Windows、または製品 ready の証拠に置き換えない。

## 境界と起動

- ユーザー提供のローカル key file を `--key-file` で launcher のみに読み込んだ。file は 8192 bytes 以下の単一行 ASCII、`sk-` prefix、非空白として検証される。値および個人用 path は記録しない。`OPENAI_API_KEY_FILE` は未指定時の fallback で、明示 file が優先する。
- key は Bridge の `OPENAI_API_KEY` 環境だけに置き、Brain 子 process には `OPENAI_API_KEY` と `OPENAI_API_KEY_FILE` を渡さない。UI、設定、ログ、引数値には保存しない。`doctor` は非課金・非 TCP のままである。
- 標準 port は HTTP/WS `8771`、Bridge TCP `8770`。今回だけ HTTP/WS `18771`、Bridge TCP `18770`、Brain `18767` を使用した。launcher の process 生成→Brain READY は 723.75 ms（純粋な initialize ではない）。単一時点の RSS は Brain 144768 KiB (141.375 MiB)、Bridge 41680 KiB (40.703125 MiB) であり、peak 値ではない。
- Brain の source/data/config hash、seed、数値モデル、刺激、decoder は既存 MOCK 記録と同じ条件であり、今回の live 検証のための変更はない。

起動コマンド（個人用 key path のみ伏せる）:

```sh
.venv-bridge/bin/python tools/dev.py up --profile mac-local --local artifacts/bridge-validation/local.json --conversation live --key-file /path/to/private-key.txt --launch-brain
```

local.json は上記専用portと既存Brain Pythonを指定するGit外設定。Brain source/config/graphの期待hashはdoctorで照合。Bridge Python 3.10 / aiohttp 3.14.3、Brain NumPy 1.24.3、seed 20270101、window 50ms、dt 0.1msは前記履歴と同じ。

## 実 API 結果

- GPT-Live session と client delegation、Responses 意図翻訳、実 MaleCNS への Action 適用を確認した。
- 初回の 5 movement Action はすべて期待する神経符号で pass。初回 `STOP` は 4 秒 TTL が翻訳待ちを無効化し safety STOP が動作したため timeout となった。これは適用成功として数えない。
- 次の明示 8 秒 `FORWARD` → 即 `STOP` では、GPT 由来 `brain_applied` がそれぞれ 2341.66 ms / 1856.17 ms、STOP motor は forward=0、turn=0、100 frames、最大 forward=0.89317、errors=0 だった。
- 日本語の合成音声から Live transcript / delegation / Responses / 実 Brain `FORWARD` 適用までを確認した。Bridge 内の適用時間は 293.99 ms。受信音声は 984000 bytes、文字のみの会話でも 619200 bytes を受信した。
- 無音補完前はマイク off 時に Live の clock が進まず返答音声 0 だった。live 中の 100 ms 無音補完・paced 送信と、音声 queue の旧 context 破棄を追加後、実 API を再検証して pass した。無音は transport clock 用であり、発話や Brain 入力を捏造しない。
- 後半試験の最初のGPT Action送信→診断終了の緊急停止まで、19.617秒wall中の86 Brain frameで50ms step wall mean 227.73ms、median 220.63ms、p95 276.94ms。p95は昇順 `floor(.95*N)`、API推論・身体動作時間を含まない。脳の高速化／decoder調整はしていない。

測定 artifact は Git 外の `artifacts/bridge-validation/live_api_probe.json`、`live_e2e_result.json`、`live_audio_text_e2e.json`。この診断結果だけには合成した検証発話・返答字幕の抜粋を保存した。音声payloadとkeyは保存していない。通常runtimeの本文・音声保存は引き続き無効。

## Browser UI と残る gate

- プレイヤー UI の原本は `Runtime/Player/`。Bridge の `GET /player/` は同一 loopback origin で配信し、`/ws` を共用する。`/` の診断画面は残す。`Runtime/Player/dist/player.html` は生成した場合だけの artifact である。
- Browser 操作では `GET /player/` 配信、Bridge 接続、`LIVE` / `MALECNS_EXPERIMENTAL` 表示、owner の `gpt` 切替、会話開始確認 dialog の表示までを確認した。実会話開始の最終 confirm はキャンセルしたため、この UI 操作では課金 API を呼んでいない。backend の実 API 往復は inline WS で別途完了済みである。
- UI は別担当が実映像・アイコン・声中心の簡素化へ改修中で、同じ `/player/` / `/ws` 契約で接続可能であること以外、新UIのDOM操作、音声操作、スピーカー再生は未検証。実マイク録音、echo 抑止、Windows Unity、実身体、Mac/Windows 間の切替、操作感も未検証。live API の接続・適用成功だけでは `ready=false` を変更しない。
