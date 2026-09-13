# Unityアプリ起動・終了連動の実装と検証

更新日：2026-09-13。通常起動は[起動手順](Unity-Startup-Handoff.md)を参照。

## 実装

正式シーンの `ConversationNativeBootstrap` はビルドdefineや引数がなくてもネイティブ構成へopt-inする。exe直接起動でローカル設定を発見し、WindowsのBrain・Bridgeを起動する。Bridge接続後の既存自動開始処理でGPT Liveのchat_only会話を開始する。起動そのものでは身体制御を有効にしない。

Unityは実行中の `Application.runInBackground` を有効にし、ウィンドウのフォーカスを失っただけでheartbeatが途絶えることを防ぐ。通常終了・Play Mode終了はstop marker、異常終了は外部ヘルパーがUnityのPIDと生成時刻を照合して検出する。heartbeat喪失も既定10秒で終了対象になる。

ヘルパーはBridgeを生成する前に自身をWindows Job Objectへ登録する。Jobは匿名、handle非継承、`KILL_ON_JOB_CLOSE` とし、子孫のBridge・Brainは自動的に同じJobへ入る。既存の別サービスをJobへ追加しない。Job登録に失敗した場合は子プロセスを起動しない。

終了要求時はshutdown fileでBridgeのGPT Live API接続の終了を要求し、最大5秒待つ。ヘルパーのプロセス終了時に最後のJob handleが閉じ、応答しない所有子孫もOSが終了する。ヘルパー自身が強制終了した場合も同じOSの後片付けが働く。GPT Liveについて終了するのはアプリのAPI接続・会話であり、外部クラウドサービス自体ではない。

`Owned` は旧検証ツールのimport互換のため残したが、通常起動の後片付けはJob Objectを使用する。

## 検証条件

- Windows／Unity 6000.5.9f1、Windows x64 Development Build。
- Python 3.10.12、psutil 7.2.2。Brain環境はPython 3.10.12、numpy 1.24.3。
- 実Windows Brain `127.0.0.1:18766`、Bridge motor `18770`、control `18771`。
- 実GPT Live API。マイク取り込みなし、固定motor・Replay・mockへの置換なし。
- exeをランチャー・`-flyConversation`・`-flyRepoRoot`なしで直接起動。cwdもリポジトリ直下以外。
- GPT Liveの自動開始は会話live状態、返信音声byte数、字幕更新の受信で確認。
- 終了はPIDと生成時刻を記録した所有プロセスの消滅、および3ポートの解放で確認。検証失敗後の掃除を成功結果へ含めない。

## 実測

| ケース | Brain sequence | GPT Live自動開始 | 所有プロセス／ポート残留 | 終了後の確認時間 |
|---|---|---|---|---|
| Unity正常終了 | 9 → 152 | 確認 | 0／0 | 2.500秒 |
| 会話接続中のUnity強制終了 | 4 → 145 | 確認 | 0／0 | 3.015秒 |
| 起動途中のUnity強制終了 | 受信前に終了 | 開始前に終了 | 0／0 | 1.953秒 |
| 監視ヘルパー強制終了 | 7 → 146 | 確認 | 0／0 | サービス0.297秒、検証Player終了まで0.438秒 |

正常・強制終了試験は各60サンプル、全て `MALECNS_EXPERIMENTAL`／`LIVE`、Brain ready=falseを維持。sequence進行を確認し、採取サンプルにprotocol errorは0。プロセスツリーの最大RSSは正常終了1,137,885,184 bytes、強制終了1,152,720,896 bytes。Brain計算速度や刺激から身体までのE2Eは本試験では測定していない。

単体テスト10件により、設定・PID再利用の照合・既存ポート保護・秘密環境変数の除去に加え、Job ownerの通常終了、強制終了時の子・孫終了と無関係な兄弟プロセスの存続を確認した。

ヘルパー強制終了の有効結果は `helper-crash-verified/`。初回の `helper-crash/` は検証スクリプトがUnity自身のCrashHandlerをBridge／Brainと誤認し、Playerを閉じずタイムアウトした。検証側をヘルパーの子孫に限定して修正し、再実行した。稼働コードの変更や失敗後の強制掃除で成功としたものではない。

## 証拠と再実行

Git除外の `artifacts/native-lifecycle/` にsource/config/data hash（`source.json`）、各試験の `lifecycle.json`、UI観測 `report.json`、PNG、Playerログを保存した。実行ソースには未コミット差分があるためHEADだけを実行内容とみなさない。

```powershell
.\.venv-bridge\Scripts\python.exe -m unittest tools.test_windows_native
.\.venv-bridge\Scripts\python.exe tools/verify_native_lifecycle.py --mode normal --output artifacts/native-lifecycle/normal-new
.\.venv-bridge\Scripts\python.exe tools/verify_native_lifecycle.py --mode player-crash --output artifacts/native-lifecycle/player-crash-new
.\.venv-bridge\Scripts\python.exe tools/verify_native_lifecycle.py --mode startup-crash --output artifacts/native-lifecycle/startup-crash-new
.\.venv-bridge\Scripts\python.exe tools/verify_native_lifecycle.py --mode helper-crash --output artifacts/native-lifecycle/helper-crash-new
```

実Player試験は既存Player・サービスを終了した状態で、順番に実施する。出力先には未作成のディレクトリを指定する。通常利用に検証probe引数は不要。

実マイク品質、身体操作の受入れ、長時間安定性、OS自体が応答しない状態は今回の検証対象外。
