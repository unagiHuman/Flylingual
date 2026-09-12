# Brain・GPT Live Bridge 統合手順

更新日: 2026-09-12。対象は Flylingual の Mac 検証用 Bridge と browser player である。本書は実装・運用の手順と受入れ状況を記録し、設計上の規範は [Brain・GPT Live の共通設計ルール](../Brain-GPTLive-CrossPlatform-Design.md) に従う。

## 構成と境界

共通 Python Bridge はゲーム側の localhost に bind する。Brain 互換 TCP は `127.0.0.1:8770`、player と制御 client 用 HTTP/WS は `http://127.0.0.1:8771/` と `ws://127.0.0.1:8771/ws` である。HTTPS 配下では player が同じ origin の `wss` を選ぶ。

`Runtime/Bridge/player.html` は Mac 検証用の状態表示・操作画面である。Bridge の接続状態、Brain `ready`、target/backend、control owner、出力抑止、frame age、forward/turn、Brain 要約、会話字幕を表示する。未知 message はログへ表示して処理を継続する。ブラウザから Brain TCP へ直接接続しない。

GPT Live は Realtime API とは別の会話経路として扱う。live の接続先・モデルは `wss://api.openai.com/v1/live/sessions` / `gpt-live-1`、意図翻訳は `gpt-5.6-luna` とし、`OPENAI_API_KEY` は Bridge ホストの環境変数だけから読む。公式の接続仕様は [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation) と [Voice WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets) を参照する。API key を player、Unity、設定ファイル、ログへ入力・保存しない。

会話モードは `off` / `mock` / `live`。`mock` は厳密な辞書による意図変換で、外部 API を使用しない。`conversation_start` は player の明示操作だけで発行し、live 会話の利用には課金が発生し得ることを画面で確認する。

## Mac ローカル起動

Bridge 用 Python は既存 Brain の環境と分離した `.venv-bridge` を使う。依存は `Runtime/Bridge/requirements.txt` の `aiohttp==3.14.3` とする。graph の `body_ids.npy`、`indptr.npy`、`targets.npy`、`weights.npy` は大容量のため Git 外で配置し、doctor の hash 検査対象にする。

```sh
python3 -m venv .venv-bridge
.venv-bridge/bin/python -m pip install -r Runtime/Bridge/requirements.txt
.venv-bridge/bin/python tools/dev.py doctor --profile mac-local --conversation mock
.venv-bridge/bin/python tools/dev.py up --profile mac-local --conversation mock --launch-brain --brain-python /path/to/brain-python
```

`/path/to/brain-python` は `Brain/MaleCNS/requirements-runtime.txt` を導入した各端末のPythonへ置き換える。Bridge専用venvにはNumPy等のBrain依存を入れていないため、既存Brain環境を指定するか、別のBrain用venvを構築する。BridgeのPythonは3.10以上。Windowsでは `.venv-bridge\Scripts\python.exe` とその端末のBrain Pythonを使う（Windowsでの実行は未検証）。既存8766サーバーを勝手に停止しない。旧serverには拡張identity/releaseがないため、新しい `brain_server_bridge.py` が必要。

liveへ進む場合は、Bridgeを起動する端末の環境に `OPENAI_API_KEY` を安全に設定し、doctor/upの `--conversation mock` を `--conversation live` へ変更する。ブラウザの「会話開始」で初めてGPT-Liveのsessionを開始する。音声はlive接続後の「音声開始」でマイク権限を与える。ヘッドホンを推奨する。音声とテキストはOpenAIへ送信されるが、Bridgeでは本文・音声を既定で保存しない。実APIが使えない場合にmockへ自動切替はしない。

実際の引数は `tools/dev.py --help`、`tools/dev.py doctor --help`、`tools/dev.py up --help` とソースを正本として確認する。`doctor` は設定・依存・graph metadata の診断だけで、TCP 接続や課金 API を実行しない。`--launch-brain` は local profile の自己所有 Brain だけを起動・終了し、remote process は管理しない。

ブラウザで `http://127.0.0.1:8771/` を開き、接続先 profile を選択して「接続」を押す。接続後も初期状態は `output inhibited=true` のままである。操作確認は次の順序に限定する。

1. `observer` / `manual` / `gpt` の owner を明示選択する。
2. 新しい fresh frame と停止状態を確認する。
3. `manual` または `gpt` を選び、画面の「明示再開」を押す。
4. manual では6 Actionボタンを使う。日本語で操作する場合は、先に「会話開始」を押し、gpt ownerを選択して明示再開する。受付、Brain適用、神経応答、身体動作を別々に記録する。
5. 切替・切断・stale・緊急停止では抑止を維持する。緊急停止は通常の神経休止 `STOP` と異なり、resume までラッチされる。

音声操作は **gpt owner選択 → 会話開始 → 明示再開 → 音声開始** の順。epoch変更後に古い未文字起こし音声が操作へ混入するのを避けるため、`voiceControlAvailable=false` では音声由来Actionを拒否する。抑止や接続先切替後は「会話停止 → 会話開始」で音声sessionを新しくしてから明示再開する。会話は接続先切替中も継続できるが、旧音声からの操作は復活しない。文字操作はこの音声session制限とは独立している。

既定 TTL は 4 秒、上限 8 秒、fresh 判定は 750 ms。期限切れ、旧 epoch、非所有者、重複 command は fail-closed で拒否する。profile 切替は出力抑止 → 旧 Brain STOP 試行 → release 確認 → session/epoch 更新 → 旧 frame/request 破棄 → 新 target 確認 → 明示 resume の順序を守る。

## remote profile と禁止事項

`windows-to-mac` は既存 SSH tunnel の localhost `18766`、`mac-to-windows` は localhost `28766` を使う。トンネルの遠隔 endpoint は各 OS の Brain に対応させ、Bridge は localhost endpoint だけを見る。無認証 LAN 接続、LAN への Bridge bind、remote process の勝手な起動・停止は禁止する。

```sh
.venv-bridge/bin/python tools/dev.py doctor --profile windows-to-mac --conversation mock
.venv-bridge/bin/python tools/dev.py up --profile windows-to-mac --conversation mock
```

## 受入れ状況

### 実装済み

- 共通設定の profile、localhost TCP/HTTP/WS のポート方針、control owner、TTL/stale の設定値。
- Brain adapter、制御 arbiter、観測要約、厳密 mock 意図辞書、および Mac player の表示・操作契約。
- player の初期抑止、切断時の旧 frame 破棄、音声停止、未知 message の非 fatal ログ。
- GPT-Liveのprimary WebSocket、client delegation、Responses structured intent、PCM16 mono 24kHz入出力。これは実装状況であり、実APIの疎通証明ではない。

### Mac実Brainで確認済み

- 日本語入力→会話MOCK→既存刺激→実MaleCNS→観測要約。6 Actionの期待符号は6/6。数値モデル・刺激・decoderは変更していない。
- controller解放を確認したlocal profile往復、新session 3個、明示resume。これは同一Mac/同一endpointを使ったlifecycle検証であり、Windows往復ではない。
- 単一制御WS、旧epoch/重複/owner競合拒否、4秒TTL、緊急停止、Brainを1.2秒止めた実stale、TCP disconnect、会話停止のmanual/GPT差分。
- Unity互換TCPのrequestId写像と、同一sequenceを待ったTCP/WS間のmotor・raw・brain完全一致。Unityそのものの試験ではない。
- [実測記録](Bridge-Validation-2026-09-12.md)に測定母数・hash・未検証gateを記載する。

### 実 API 未検証

- `gpt-live-1` live session、client delegation、音声往復、`gpt-5.6-luna` 意図翻訳。
- 実 API key は未提供であり、課金 API は本手順では呼び出していない。mock の合格を live の合格に読み替えない。

### Windows 未検証

- Unity `AudioAdapter`、Unity 側出力抑止、Windows ゲーム、実身体、Windows 実機での TCP/WS 統合と操作感。
- この画面は Mac 検証用であり、実身体は未接続である。「気持ち」は観測に基づく擬人化表現で、感情測定ではない。

raw BrainFrame、原本ID、対応ID、epoch、適用時間は `logPath` へ記録する。本文・音声は保存しない。ログは32MiB×本体とバックアップ2本でローテーションする。
