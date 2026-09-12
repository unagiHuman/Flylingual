# Flylingual Unity 起動・シーン申し送り

更新日：2026-09-13（JST）
対象：`Flylingual/UnityProject`、Unity `6000.5.5f1`

## 先に確認すること

Unityの起動シーンは用途によって異なります。通常のBuild Settingsの先頭シーンと、ネイティブ会話Playerが明示的にビルドするシーンを混同しないでください。

| 用途 | シーン | 起動・ビルド方法 |
|---|---|---|
| 通常のBuild Settings先頭 | `Assets/Scenes/FlyLocomotionSandbox.unity` | `ProjectSettings/EditorBuildSettings.asset`で有効。通常のUnity起動・基礎移動確認用 |
| Windowsネイティブ会話Player | `Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity` | `NativeConversationBuilder.Build()`がこのシーンを明示指定してビルド |
| ネイティブ会話の独立Editor検証 | `Assets/RuntimeIntegration/Conversation/NativeConversationTest.unity` | 専用テストシーン。Bridge接続、音声部品、状態遷移の確認用 |
| 旧Replay／物理検証 | `Assets/VisualDemo/WindowsReplayDemo.unity` | 旧Replay確認用。ネイティブ会話の通常起動には使わない |

ネイティブ会話Playerは `EditorBuildSettings.asset` の先頭シーンから起動するのではなく、ビルドスクリプトの指定に従います。したがって通常の先頭シーンを変更しても、ネイティブ会話Playerの起動シーンは自動では変わりません。

## 初回設定

リポジトリルートで実行します。秘密鍵の内容は設定ファイル・Unity引数・Gitへ書き込みません。

```powershell
Copy-Item Runtime/Config/windows-native.example.json Runtime/Config/windows-native.local.json
notepad Runtime/Config/windows-native.local.json
```

最低限、次を実在するWindowsパスに合わせます。

- `bridgePython`：通常は `.venv-bridge/Scripts/python.exe`
- `bridgeLocalConfig`：通常は `Runtime/Config/local.json`
- `keyFile`：外部APIキーを1行だけ保存したGit除外ファイル
- `runRoot`：生成ログの保存先。通常は `artifacts/windows-native-runs`

未導入の場合は、Bridge側の依存を準備します。

```powershell
uv pip install --python .venv-bridge/Scripts/python.exe -r tools/requirements-windows-native.txt
```

## Windows Playerをビルドする

Unity Hub／Editorで `UnityProject` を `6000.5.5f1` で開き、次のメニューを実行します。

`Flylingual > Conversation > Build Windows conversation Player`

この処理は次を行います。

- シーン：`Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity`
- Target：`StandaloneWindows64`
- Define：`FLY_NATIVE_CONVERSATION`
- 出力：`artifacts/windows-native-conversation/unity/FlylingualConversation.exe`

CLIからは次の形式です。

```powershell
unity build UnityProject --editor-version 6000.5.5f1 --target StandaloneWindows64 --execute-method NativeConversationBuilder.Build
```

実際のPlayerビルドが必要なため、既存exeがあるだけでは最新C#変更を含むとは判断しません。

## ネイティブ会話Playerを起動する

```powershell
.\Start-UnityConversation.cmd
```

このlauncherはPlayerに `-flyConversation` とリポジトリルートを渡します。Player内の `ConversationNativeBootstrap` が `tools/windows_native.py` を起動し、自分が所有するBrain／Bridgeだけを管理します。既存プロセスの一括killや、ブラウザ・WebRTCの起動は行いません。

画面サイズなどを追加する場合は、launcherの後ろに渡します。

```powershell
.\Start-UnityConversation.cmd -screen-width 1280 -screen-height 720
```

マイクなしの受信専用確認は次の引数を付けます。

```powershell
.\Start-UnityConversation.cmd -flyConversationNoMicrophone
```

通常起動ではBridge接続後に会話のみモード（`chat_only`）を開始します。会話のみでは身体出力を抑止します。「声で操作を有効にする」は別の明示操作であり、Brainのfresh STOP、control owner、resume条件を満たさない限り身体は動きません。起動しただけで実マイク入力や身体操作の受入れ完了とは扱いません。

Player終了時はUnityがstop markerを作成し、Bridgeの会話とPlayerが起動した子プロセスを終了します。通常のウィンドウ終了を使い、所有者不明のプロセスを一括killしないでください。

## Editorでネイティブ会話を確認する

1. Unityで `Assets/RuntimeIntegration/Conversation/NativeConversationTest.unity` を開く。
2. `Play` を押す。
3. `ConversationNativeBootstrap` がEditor用のScene opt-inとして動作し、`windows-native.local.json`（なければ`windows-stack.local.json`）を読み込む。
4. Bridge接続後、会話UI・字幕・音声診断・停止を確認する。

このテストシーンは独立したカメラ、AudioListener、会話Bootstrapを持つ軽量シーンです。通常の3D身体表示を含むPlayerビルドの代わりではありません。身体表示を含むPlayerは `FlyGroundedRealismDemo.unity` を使用します。

## 起動時の注意

- ネイティブ会話Playerの確認中は、旧ブラウザPlayerや別のcontrol WebSocketを同時に開かない。control WebSocketは単一接続です。
- `Start-WindowsLocal.cmd` は旧WebRTC／ブラウザを含むWindows-local構成用で、ネイティブ会話Playerの通常起動には使わない。
- `127.0.0.1:18770` はネイティブ会話PlayerがBridgeのmotor経路へ接続するポート。会話制御とBrain接続は同居Bridge経由で管理する。
- `ready=false`、750ms freshness、stale時の出力抑止は仕様として維持する。接続できたことだけでBrain readyやGameplay成功に昇格させない。
- 起動に失敗した場合は、まずPlayerのログ、`artifacts/windows-native-runs`、local設定の存在を確認する。APIキー本文をログへコピーしない。

## 申し送り時の確認項目

- [ ] Unity Editorの版が `6000.5.5f1`
- [ ] Build Settingsの先頭が必要なら `FlyLocomotionSandbox.unity`
- [ ] ネイティブ会話Playerのビルド対象が `FlyGroundedRealismDemo.unity`
- [ ] `windows-native.local.json` がGit除外で存在する
- [ ] Player exeが `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` にある
- [ ] 起動後のBrain／Bridge／会話状態を画面診断で確認した
- [ ] 未検証の実マイク10往復、AEC、会話＋身体操作、移動品質を成功扱いしていない
