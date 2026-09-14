# Flylingual Unity 起動・シーン申し送り

更新日：2026-09-13（JST）
対象：`Flylingual/UnityProject`、Unity `6000.5.9f1`（`ProjectSettings/ProjectVersion.txt`）

## 通常の起動方法

このPCではBlind Sugar RunのStart Areaから始まるWindows Playerをビルド済みです。`artifacts/windows-native-conversation/unity/FlylingualConversation.exe` をダブルクリックすると、新しいプロトステージが開き、Unityアプリ自身がBrain・Bridge・GPT Live会話を自動起動します。先に別のサービスや起動スクリプトを実行する必要はありません。現在は開発用に3Dを表示し、Blind UI・新Goalのクリア判定・Final Revealは後続Phaseです。

PowerShellでexeを直接起動する場合：

```powershell
& 'C:\Users\tiger\UnityProj\Fly\FlyTest\Flylingual\artifacts\windows-native-conversation\unity\FlylingualConversation.exe'
```

画面サイズなどの引数を付けやすい従来の `Start-UnityConversation.cmd` も使用できます。起動・終了管理の本体はUnityアプリ側です。

```powershell
Set-Location C:\Users\tiger\UnityProj\Fly\FlyTest\Flylingual
.\Start-UnityConversation.cmd
```

起動すると、左にゲーム映像全体の縮小表示、右上に脳・神経活動、右下にハエリンガルのポンチ絵が表示されます。会話・停止ボタンと字幕は下部、「設定と診断」は右下です。ハエリンガルは現在、会話状態を表現します。思考・感情を脳活動から推定する機能は未実装です。

UnityがWindowsローカルのBrain／Bridgeを起動します。通常起動のためにUnity Editor、ブラウザ、WebRTC、Mac側Brainを別途起動する必要はありません。GPT Live／Responsesへの外部API接続は必要です。

Bridgeの準備ができると会話のみ（`chat_only`）を自動開始し、通常はマイク収録・送信も開始します。身体出力は抑止したままです。「声で操作を有効にする」は別の明示操作で、Brainのready／fresh STOP、control owner、resume条件を満たす必要があります。

画面サイズを指定する場合：

```powershell
.\Start-UnityConversation.cmd -screen-width 1280 -screen-height 720
```

マイクを使わずに画面・受信を確認する場合：

```powershell
.\Start-UnityConversation.cmd -flyConversationNoMicrophone
```

この引数ではミュート解除でも録音しません。通常の会話では付けません。検証専用の `-playScreenProbe`／`-playScreenProbeQuit` は通常起動には不要です。

終了はPlayerウィンドウを閉じます。Unityが正常終了した場合も、クラッシュ・タスク終了で消えた場合も、監視ヘルパーがこの起動に属するBrain／Bridgeを終了します。GPT LiveはBridgeが所有する外部APIセッションであり、Bridge終了に伴って接続が閉じます。クラウド側のサービスそのものを停止する操作ではありません。

正常終了はstop marker、異常終了はUnityのPIDと生成時刻の不一致で検出します。通常稼働中の監視間隔は約250msで、終了要求後は最大5秒の正常終了猶予を置きます。応答しない子孫や監視ヘルパー自体の異常終了は、Windows Job Objectの `KILL_ON_JOB_CLOSE` により後片付けします。既存の別プロセスを一括終了しません。

「会話を終了」は会話だけを止める操作で、PlayerやBrainの終了とは異なります。ウィンドウを背面にするだけでは終了しません。Unityのheartbeatが既定10秒途絶えた場合も監視ヘルパーは後片付けします。

## 通常版と検証用ビルドの更新先

通常起動先は `artifacts/windows-native-conversation/unity/FlylingualConversation.exe`。`NativeConversationBuilder.Build()` でこのファイルを更新する。`HayeringualBuildWindow.Build(Dev, Local)` の出力は別の `artifacts/hayeringual-builds/Dev-Local/` であり、通常版の更新にはならない。

通常版を更新した後の実Brain検証は、runnerに `-NativePlayer` を付けて同じexeを起動する。以下は実GPT Live/APIを使うマイクなしの診断試験で、通常の遊び方ではない。

```powershell
& tools/neural_player_trial.ps1 -Name native-swatter-fix -Language ja -Question 0 -ConnectionStability -NativePlayer -RenderScreenshot
```

既存の試験名は上書きせず、新しい名前を使う。2026-09-14の通常版更新漏れと検証は [Windows Player更新記録](Native-Player-Swatter-Fix.md) を参照。

## 初回設定・別PCでの準備

設定済みの本PCでは既存local設定を使用します。ランチャーは `Runtime/Config/windows-native.local.json` を優先し、なければ `Runtime/Config/windows-stack.local.json` を使用します。既存ファイルへexampleを上書きしないでください。

両方とも存在しない環境でのみ、リポジトリ直下から設定を作成します。

```powershell
if (!(Test-Path Runtime/Config/windows-native.local.json) -and !(Test-Path Runtime/Config/windows-stack.local.json)) {
    Copy-Item Runtime/Config/windows-native.example.json Runtime/Config/windows-native.local.json
}
```

使用するlocal設定内のパスを、そのPCに合わせます。

- `bridgePython`：通常は `.venv-bridge/Scripts/python.exe`
- `bridgeLocalConfig`：通常は `Runtime/Config/local.json`。Windows側Brainの起動設定を含む
- `keyFile`：外部APIキーを1行保存したファイルのパス
- `runRoot`：通常は `artifacts/windows-native-runs`

キー本文は引数・ログ・Gitへ書きません。Python環境が準備済みで追加依存が未導入の場合は、次を実行します。

```powershell
uv pip install --python .venv-bridge/Scripts/python.exe -r tools/requirements-windows-native.txt
```

脳の実座標表示には、Git除外の `UnityProject/Assets/BrainVisualization/Resources/BrainVisualization/malecns-atlas.json` が必要です。本PCは配置済みで、`Runtime/Config/local.json` の `brain.visualizationAtlas` も設定済みです。別PCではGit取得だけで原データ・生成atlas・Python環境が揃うわけではありません。生成元と設定項目は[実装記録](Play-Screen-Implementation.md)を参照してください。

## 最新ソースからWindows Playerをビルドする

1. `UnityProject` をUnity `6000.5.9f1`で開く。
2. Play Modeを停止する。
3. `Flylingual > Play Screen > Build Windows Player` を実行する。
4. ビルド成功後、`Start-UnityConversation.cmd`で起動する。

ビルド対象は `Assets/BlindSugarRunPrototype/BlindSugarRunPlay.unity`、出力先は `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` です。`PlayScreenBuilder.Build()`がシーンを明示指定し、Windows x64、`FLY_NATIVE_CONVERSATION`、Development Buildで生成します。Player用の文字描画データを含むPanelSettingsアセットも用意します。

従来の `Flylingual > Conversation > Build Windows conversation Player` も現在は同じ正式シーンを対象としますが、通常の再ビルド手順は上記のPlay Screenメニューです。既存exeはソース編集だけでは更新されません。

## Editorで正式プレイ画面を確認する

1. Playerを終了してからUnityで `Assets/BlindSugarRunPrototype/BlindSugarRunPlay.unity` を開く。
2. `Play`を押す。
3. シーン内の `ConversationNativeBootstrap` がEditor用のScene opt-inとして動作し、Playerと同じlocal設定を読む。
4. 3領域、接続状態、字幕、設定と診断を確認する。
5. 確認後はPlay Modeを停止する。

起動シーンは既存の正式プレイシーンの身体・会話・Brain連携を保持し、地形を置換して生成済みです。毎回の起動で生成メニューを実行する必要はありません。`Create formal play scene` は旧シーンを再生成するメニューなので、新ステージの起動には使いません。新規起動シーンの初回生成用は `Flylingual > Blind Sugar Run > Create startup scene` で、既存の起動シーンがある場合は上書きせず停止します。

| 用途 | シーン／方法 |
|---|---|
| 正式プレイ画面（Player・Editor） | `Assets/BlindSugarRunPrototype/BlindSugarRunPlay.unity` |
| 環境のみの独立プロトScene | `Assets/BlindSugarRunPrototype/BlindSugarRunPrototype.unity`。Fly・会話は含まない |
| 起動シーンの身体・統合機能の複製元 | `Assets/RuntimeIntegration/PlayScreen/FlylingualPlay.unity`。元シーンは保持 |
| 会話部品の独立検証 | `Assets/RuntimeIntegration/Conversation/NativeConversationTest.unity`。正式3Dプレイ画面の確認用ではない |
| 正式シーンの生成元 | `Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity` |
| 基礎移動用シーン | `Assets/Scenes/FlyLocomotionSandbox.unity`。正式Playerの起動先ではない |

EditorBuildSettingsの先頭も新しい起動シーンに設定済みです。専用ビルダーは別途シーンを明示指定するため、今後起動先を変更するときは両方をそろえます。

## 起動確認とトラブル時

- `Start-WindowsLocal.cmd` はブラウザ／WebRTC構成用です。正式ネイティブPlayerと同時に起動しません。control WebSocketは単一接続です。
- Windows Brainは `127.0.0.1:18766`。Playerの `127.0.0.1:18770` はBridge motor TCPであり、Brainへ直接つなぐポートではありません。
- ヘッダーの会話準備とBrain readyを区別します。`ready=false`やstale時は表示を偽装せず、身体出力を抑止します。
- exeが見つからない場合は上記ビルドを実施します。local設定が見つからない場合は初回設定を確認します。
- 起動に失敗した場合はPlayerログと `artifacts/windows-native-runs`、設定で指定したパスを確認します。ログを指定する例は `.\Start-UnityConversation.cmd -logFile C:/Users/tiger/UnityProj/Fly/FlyTest/Flylingual/artifacts/play-screen-user.log` です。
- 既存ポートを使う所有者不明のプロセスを一括終了せず、重複して起動した自分のPlayerやローカル構成を正常終了します。

1920×1080／1280×720の表示、実Brain受信、設定パネル開閉は確認済みです。実マイク10往復、音声による身体操作、移動品質、非ゼロ発火の表示、長時間安定性はこの画面検証から合格とはしません。

詳しい操作は[ネイティブ会話の利用手順](Unity-Native-Conversation-Usage.md)、画面構成は[インターフェース仕様書](Play-Screen-Interface-Spec.md)、実測は[実装・検証記録](Play-Screen-Implementation.md)を参照してください。

アプリとサービスの終了連動は、正常終了・Unity強制終了・起動途中・監視ヘルパー強制終了を実機確認済みです。[終了連動の検証記録](Unity-Lifecycle-Validation.md)を参照してください。
