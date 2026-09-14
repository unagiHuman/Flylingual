# Flylingual Mac 起動申し送り

更新日：2026-09-13（JST）

これは [Windows Unity 起動・シーン申し送り](../windows/Unity-Startup-Handoff.md) に対応する、Mac側のBrain・Bridge・Unity会話Player起動手順です。Mac側の正式な入口は、MaleCNS Brain、共通 Bridge、Unity会話Playerをまとめて起動するMac Playerです。

## Mac側の構成

| 用途 | Mac側の入口 | ポート／シーン |
|---|---|---|
| Brain | `Brain/MaleCNS/brain_server_bridge.py` | `127.0.0.1:8766` |
| Bridge TCP | `tools/dev.py` | `127.0.0.1:8770` |
| 診断・操作画面 | ブラウザ `Runtime/Bridge/player.html` | `http://127.0.0.1:8771/` |
| Player UI | ブラウザ `Runtime/Player/` | `http://127.0.0.1:8771/player/` |
| Unity会話Player | `FlylingualConversation.app` | `artifacts/mac-native-conversation/unity/` |

ブラウザはBrain TCPへ直接接続せず、Bridgeのlocalhostだけを使います。起動直後は出力抑止中です。`ready=false` は現在のMaleCNSが実験ランタイムであり、接続成功だけでは身体動作の受入れにならないことを示します。

## 初回だけ行う設定

リポジトリルートで実行します。

```sh
cd /Users/isaoohta/UnityGame/FlyBrain/Flylingual
"$HOME/miniforge3/envs/flybrain-malecns/bin/python" -m venv .venv-bridge
.venv-bridge/bin/python -m pip install -r Runtime/Bridge/requirements.txt
.venv-bridge/bin/python -m pip install -r tools/requirements-mac-native.txt
"$HOME/miniforge3/envs/flybrain-malecns/bin/python" -m pip install -r Brain/MaleCNS/requirements-runtime.txt
```

Brain用PythonはBridge用venvと分離します。別のPythonを使う場合は、`Brain/MaleCNS/requirements-runtime.txt` を導入したPython 3.10環境を用意して `FLY_BRAIN_PYTHON` または `--brain-python` で指定します。API keyはこの設定やGitへ保存しません。

Unityから自動起動する場合は、Git管理外のMac設定を作成します。

```sh
cp Runtime/Config/mac-native.example.json Runtime/Config/mac-native.local.json
```

`mac-native.local.json` の `bridgePython`、`brainPython` をこのMacの実在するPythonへ合わせます。初期値の `conversationMode` は `mock` のままにし、liveへ切り替える場合だけ `keyFile` を追加します。

## Unityだけを起動入口にする

Unity Editorで次のメニューを実行します。

`Flylingual > Conversation > Build Mac conversation Player`

出力先は次です。

```text
artifacts/mac-native-conversation/unity/FlylingualConversation.app
```

このMac Playerは起動時に `tools/mac_native.py` を自分のSupervisorとして起動し、そこからMac-local BrainとBridgeを所有起動します。Unity内の会話UI、字幕、マイク、音声再生、Bridge WebSocket、Brain motor接続は既存のConversation実装を使用します。Unity終了時はstop markerを送り、自分が起動したプロセスだけを終了します。

## ターミナルからの診断起動

Unity Playerを使わずBrainとBridgeだけを確認する場合は、従来の入口を使えます。

```sh
cd /Users/isaoohta/UnityGame/FlyBrain/Flylingual
./tools/Start-MacLocal.sh
```

既定は外部APIを使わない `mock` 会話です。起動後にブラウザで次を開きます。

```text
http://127.0.0.1:8771/
```

終了は起動したターミナルで `Ctrl-C` を押します。ランチャーは自分が起動したBrainだけを終了し、既存の別プロセスを一括停止しません。8766が既に使用中の場合も、既存Brainを勝手に停止せず起動失敗として扱います。

実APIを使う場合だけ、ローカルの単一行key fileを明示します。値は引数やログへ展開されません。

```sh
./tools/Start-MacLocal.sh --conversation live --key-file "$HOME/.config/flylingual/openai-key.txt"
```

`conversation_start`、会話開始、音声開始はブラウザで明示操作します。実APIは課金が発生し得るため、mock確認から切り替えます。実API障害時にmockへ自動フォールバックしません。

## 既存Brainへ接続する場合

既に自分で管理している `127.0.0.1:8766` のBrainへBridgeだけを接続する場合に限り、次を使います。

```sh
./tools/Start-MacLocal.sh --bridge-only
```

所有者不明の8766プロセスは停止・再利用しません。WindowsやSSH tunnelなどのremote profileは、このMac-localランチャーではなく `tools/dev.py` のremote profile手順を使います。

## Unityとの対応範囲

Windows申し送りのシーンはそのままMacネイティブPlayerの起動シーンにはなりません。

- 通常のUnity Editor／基礎移動確認のBuild Settings先頭は `UnityProject/Assets/Scenes/FlyLocomotionSandbox.unity` です。
- `BlindSugarRunPlay.unity` はWindows／Macの正式Conversation Player起動Sceneです。Windowsは `Play Screen > Build Windows Player`、Macは `Conversation > Build Mac conversation Player` を使います。
- `FlyGroundedRealismDemo.unity` は正式起動Sceneを生成する元Sceneであり、Playerへ直接焼き込みません。
- `NativeConversationTest.unity` はWindowsネイティブ会話の独立Editor検証用です。
- Mac用Unityネイティブ会話PlayerはBrain接続、会話UI、マイク、音声再生、身体制御の入口を持ちます。ただし実マイク、実API、継続動作、身体動作品質は別途実測が必要です。

したがってMacでは、Mac conversation Playerの起動が標準経路です。`Start-MacLocal.sh` と `http://127.0.0.1:8771/` は、Playerを使わない診断・復旧用の経路です。Unity側のWindows Playerは別マシンでWindows申し送りに従って起動します。

## 起動確認の判定

最低限、次を確認します。

1. Unity PlayerのConversation UIに `接続: connected` とBrain identityが表示される。
2. `brainConnected=true`、`backend=MALECNS_EXPERIMENTAL`、`dataset=male-cns:v1.0` を確認する。
3. 初期状態の `output inhibited=true` を確認し、owner・fresh STOP・明示resumeの順序を守る。
4. `ready=false`、実身体未接続、実マイク・実API未検証を成功扱いしない。

設定・依存・graph hashだけを確認する場合は、起動せず次を実行します。

```sh
.venv-bridge/bin/python tools/dev.py doctor --profile mac-local --conversation mock \
  --brain-python "$HOME/miniforge3/envs/flybrain-malecns/bin/python"
```

## 変更範囲

このMac起動手順はUnityの `ConversationNativeBootstrap` が `tools/mac_native.py` を呼び出し、Supervisorが `tools/dev.py` を所有起動して実現します。`tools/Start-MacLocal.sh` はPlayerを使わない診断用入口です。既存の `Work/Drosophila_brain_model`、`Work/FlyBrainUnityPoC`、別Brainサーバーは管理対象外です。Mac Player用に既存Conversationの起動処理、Macビルドメニュー、Input System依存、マイク権限説明を追加しています。
