# Windows Local Stack（Windows ローカル構成）

現在の正式ネイティブプレイ画面は `Start-UnityConversation.cmd` から起動します。[Unity起動手順](Unity-Startup-Handoff.md)を参照してください。本書はブラウザ／WebRTCを使う別構成の手順です。両方を同時に起動しないでください。

この手順は Flylingual の Windows 1 台構成を対象にします。Unity Windows Player、MaleCNS Brain、Bridge、ローカル WebRTC 映像サービス、ブラウザ Player は同じ PC の loopback で動作します。GPT Live と Responses API は Bridge から Windows の外部 OpenAI API へ接続します。この構成はオフライン代替ではありません。

## 初回設定

このWindows PCは設定済みです。リポジトリ直下の `Start-WindowsLocal.cmd` をダブルクリックすると、Brain・Bridge・映像サービス・Unityを起動し、Windowsを選択したWeb画面を開きます。既に起動中なら二重起動を拒否し、既存サービスを保持します。

PowerShellのスクリプト実行制限は変更しません。確認だけ行う場合は次を使います。

```powershell
.\.venv-video\Scripts\python.exe tools/windows_local.py doctor
```

共有 profile を変更せず、Git 除外の local 設定を使います。例の設定をコピーし、実際の Windows パスと秘密鍵パスだけを編集します。

```powershell
if (!(Test-Path Runtime/Config/windows-stack.local.json)) { Copy-Item Runtime/Config/windows-stack.example.json Runtime/Config/windows-stack.local.json }
notepad Runtime/Config/windows-stack.local.json
```

`bridgeLocalConfig`、`unityPlayer`、`videoBackendConfig`、`videoPublisherConfig` を実在するパスにし、`keyFile` は秘密鍵ファイルのパスにします。鍵の内容は設定、ログ、Unity 引数、ブラウザへコピーしません。

起動処理は `windows-local` と `unity-windows` を明示します。共有リポジトリ側に端末固有のAPIキーパスを保存しません。

- Brain: `127.0.0.1:18766`
- Bridge motor TCP: `127.0.0.1:18770`
- Bridge control/UI: `http://127.0.0.1:18771`
- Video backend: `http://127.0.0.1:8880`
- Video stream: `unity-windows`

初回起動前に doctor を実行し、必要なら既存の自分のサービスだけを停止してから再確認します。4 ポートを別プロセスが使用している場合に一括 kill はせず、所有者を確認します。

```powershell
.\.venv-video\Scripts\python.exe tools/windows_local.py doctor
.\Start-WindowsLocal.cmd
```

時間を限定する場合は `.\Start-WindowsLocal.cmd --duration 30 --no-browser` を使います。通常は起動したコンソールで `Ctrl+C` を押すと、その起動処理が所有する子プロセスも終了します。Unityが終了した場合も残りのサービスを終了します。APIキーは外部ファイルを `keyFile` で指定し、内容を設定、Unity引数、ブラウザ、ログへコピーしません。

PowerShellスクリプト実行を許可している環境では、`tools/Start-WindowsLocal.ps1 -Action up` も使えます。`-KeyFile`、`-Duration`、`-NoBrowser` はPython起動オプションに対応します。

Chrome または外部ブラウザで次の URL を開きます。query は設定を選ぶだけで、接続・マイク・control・resume を開始しません。

`http://127.0.0.1:18771/player/?profile=windows-local&stream=unity-windows&videoPort=8880`

映像を接続するときは `unity-windows` を選びます。ブラウザの control は Bridge page と同じ origin、映像はローカル video endpoint を使います。

`Runtime/Config/profiles/` のMac用・遠隔接続用profileは共有コードに残しています。このWindows用起動では使用せず、Macの起動やSSH接続を必要としません。

## Control と安全

通常の Player の「話しかける」を GPT control に使います。選択 profile へ接続し、所有権を変更し、新しい Brain STOP 適用を待ち、live conversation を開始してから明示的に 1 回だけ `resume` します。stale frame、切断、epoch 変更、会話終了後に UI は自動 resume しません。Bridge console の manual owner も、新しい停止状態を確認してから明示 resume します。temporary guard や第 2 の control WebSocket は起動しません。

Brain identity は `MALECNS_EXPERIMENTAL` / `male-cns:v1.0`、`ready=false` のままです。既存の 750 ms freshness limit と output inhibition は安全動作であり、Windows 同居で解決しません。神経妥当性、voice-to-Action、移動品質、gameplay acceptance は未認証です。

## Validation reference

新しい一括起動の180秒検証は `artifacts/windows-local-runs/20260912-214923/` に記録しました。Windows BrainとBridgeの起動、UnityへのLiveTcp連番105〜118の受信、ChromeのLIVE表示を確認し、時間終了後に4ポートが解放されました。設定・ポート競合・所有プロセス終了のテスト5件とWindows Playerビルドも成功しています。Unityの開始ボタンがLiveTcpを維持する修正はビルド確認済みですが、操作ツールがPlayerウィンドウを取得できず、そのボタンの実操作確認は未実施です。

以前のローカル検証結果は [ignored Windows runtime report](../../artifacts/windows-runtime-validation/README.md) にあります。実 GPT Live 認証、Responses 完了、Windows Unity から Chrome への WebRTC 受信、30 秒 decoded measurement を記録しています。いずれも過去の記録であり、このガイドを読むだけで新しい検証にはなりません。マイク、voice-to-body action、gameplay objective、片方向 end-to-end latency は未検証です。

## 初回起動チェックリスト

1. `.venv-video`、`windows-stack.local.json`、指定した Unity Player、publisher/backend 設定、秘密鍵ファイルを確認します。
2. `doctor` で設定と依存関係を確認します。
3. Brain `18766`、Bridge TCP `18770`、Bridge UI `18771`、Video `8880` の所有プロセスを確認します。既存の自分のプロセスがあれば、個別に graceful stop してから起動します。一括 kill はしません。
4. `up` 後に上記 URL を開き、必要なときだけ映像接続と明示的な音声開始を行います。
