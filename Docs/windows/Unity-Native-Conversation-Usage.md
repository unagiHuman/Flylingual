# Unity ネイティブ会話版の利用手順

これは Unity が3パネルのプレイ画面、会話UI、マイク、返答音声、字幕、診断表示を担当するWindows Playerです。Unity Windows Player、同居 Bridge、同居 Brain は Windows 内で動作しますが、GPT Live と Responses は Bridge から外部 OpenAI API へ接続するため、Windows の外向きネットワークが必要です。

Playerは `GAME VIEW`（左7）と、右3に上下配置した 「脳・神経活動」／「ハエリンガル」 で構成されます。ゲーム映像は16:9のRenderTextureをUI Toolkitの `ScaleToFit` で表示します。脳パネルは実atlasの24,000細胞体座標と、既存Bridge control WebSocketからの受動的なBrainFrame観測を使います。ポートレートは会話状態のポンチ絵表現であり、脳活動から感情を推定する表示ではありません。

## 対象範囲

通常起動では、ConversationSessionController が BridgeReady 後に一度だけ `EnableVoiceActions` を自動実行し、fresh STOP の適用と `resume` gate を通過した後に control session／`owner=gpt` を有効にします。これにより起動時から音声 Action を受け付けます。会話だけを使う場合は画面の「会話のみ開始」ボタンを押すか、`-flyConversationChatOnly` を明示します。`chat_only` では行動要求を Bridge 側で拒否し、身体出力を抑止します。明示停止、期限切れ、fault、切断の後は自動再開しません。実マイク10往復、15分継続、移動品質は未受入れです。`ready=false` と750msの制限は維持します。音声経路の実測状況は [検証記録](Unity-Native-Conversation-Validation.md) に記録します。

会話の責務は「音声・字幕・会話状態」、Brain／Bridge の責務は「外部 API、意図翻訳、Brain 接続、排他、安全停止」です。Unity は Brain や API へ直接接続せず、同居Bridgeの control/audio WS と、声で操作を有効にした場合の motor TCP を使います。旧ブラウザ Player や WebRTC はこの会話版に不要で、同じ Bridge へ第二の control WS を開かないでください。

## 初回準備

Unity Player の対象ファイルは次です。

`artifacts/windows-native-conversation/unity/FlylingualConversation.exe`

秘密鍵の本文は表示・コピーせず、Git 除外の local 設定にファイルパスだけを書きます。

```powershell
if (!(Test-Path Runtime/Config/windows-native.local.json) -and !(Test-Path Runtime/Config/windows-stack.local.json)) { Copy-Item Runtime/Config/windows-native.example.json Runtime/Config/windows-native.local.json }

```

既存の `windows-native.local.json`、`windows-stack.local.json`、`Runtime/Config/local.json` は上書きしません。既存設定を使う場合は内容を保持したまま、必要な端末固有パスだけを確認します。`bridgePython` は `.venv-bridge/Scripts/python.exe`、`bridgeLocalConfig` は `Runtime/Config/local.json`、`keyFile` は実際の外部キー1行ファイルにします。`windows-stack.local.json` も受け付けます。

Bridge 環境に process ownership 用依存を入れます。

```powershell
uv pip install --python .venv-bridge/Scripts/python.exe -r tools/requirements-windows-native.txt
```

ヘッドセットを推奨します。Unity の Windows `Microphone` API で収録を継続しますが、AEC／noise suppression はありません。スピーカー利用時のエコーと割込み発話の実機品質は未検証です。

Playerを最新ソースから作る手順は [Unity起動・シーン申し送り](Unity-Startup-Handoff.md) の「最新ソースからWindows Playerをビルドする」を参照してください。Unityは6000.5.9f1、正式シーンは `Assets/RuntimeIntegration/PlayScreen/FlylingualPlay.unity`、ビルドメニューは `Flylingual > Play Screen > Build Windows Player`、出力は `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` です。正式Playerのビルド、1920×1080／1280×720表示、実Brain受信、設定パネル開閉は確認済みです。[実装・検証記録](Play-Screen-Implementation.md)を参照してください。

## 起動と終了

`artifacts/windows-native-conversation/unity/FlylingualConversation.exe` を直接起動します。UnityアプリがBrain・Bridge・GPT Liveを自動開始するので、別の起動作業は不要です。従来のランチャーを使う場合は次を実行します。

```powershell
.\Start-UnityConversation.cmd
```

必要な場合は Player 引数を追加できます。

```powershell
.\Start-UnityConversation.cmd -screen-width 1280 -screen-height 720
```

`-flyConversation` により `ConversationNativeBootstrap` が Unity の所有者 PID と heartbeat を作り、`tools/windows_native.py` を起動します。helper は `windows-local`、Bridge の `Runtime/Config/local.json`、秘密鍵パスを使い、Brain／Bridge を自分が起動した子だけ管理します。既存ポートを無条件に奪ったり、一括 kill したりしません。Unity を閉じると stop marker が書かれ、Bridge の会話終了と所有子プロセスの停止が行われます。

専用exeの直接起動でも同じ初期化になります。内部サービス起動とローカル制御WS接続は自動で行い、ConversationSessionController が Ready 後に `EnableVoiceActions` を一度だけ実行します。fresh STOP／`resume` gate 完了後に音声操作を開始し、会話終了、明示停止、期限切れ、fault、切断の後は自動再開しません。`-flyConversationChatOnly` を付けた場合だけ旧来の `chat_only` 起動になります。

Unityアプリの正常終了・強制終了・クラッシュを監視ヘルパーが検出し、最大5秒の正常終了猶予後に、その起動に属するBrain／Bridge子孫をWindows Job Objectで終了します。ヘルパー自体が落ちた場合もJob Objectが子孫を終了します。GPT LiveのAPI接続もBridgeとともに閉じます。ウィンドウを背面にしただけではサービスを終了しません。

起動後は、画面上でゲーム映像、脳活動、ポートレートを同時に確認できます。脳パネルにはbackend／mode、観測数、atlas対象数、sequence、window、frame age、更新状態が表示されます。設定と診断には、マイクデバイス、音量、言語・音声・人格、表示ゲイン、Brain backend／ready、frame age、sequence、schema error、会話全文、文字指示欄が含まれます。ポートレートには会話状態と「表現の根拠」を表示します。

## 会話操作

1. 通常起動では BridgeReady 後に音声操作の初期化が一度だけ行われ、fresh STOP／`resume` gate 後に control 会話とマイク収録・送信が始まります。会話のみを選んだ場合は Bridge へ `conversation_start` と `interaction: chat_only` を送り、owner は observer のままで `resume` や Action は送信しません。
2. マイクは自動収録・送信されます。返答 PCM はマイク状態にかかわらず再生し、返答音声と認識結果を字幕に表示します。
3. GPT Live の双方向通話中は、非ゼロ返答 PCM の再生中もマイクを常時収録・送信します。返信再生とマイク送信が同時に動作しても、AEC やエコー自動除去を意味しません。
4. ミュートはマイクを解放するだけで、返答音声の再生は継続します。デバイス変更または unmute で再収録します。
5. 「会話を終了」または「身体を停止」はマイク、再生キュー、会話セッションを停止します。明示停止後は自動再開せず、音声操作を再開するには「声で操作を有効にする」をもう一度押します。WS 切断も同じく停止し、自動再開しません。WS 切断時は Player を起動し直します。

## 声による身体操作

通常起動では上記の初期化が自動で行われます。会話のみから切り替える場合、画面の「声で操作を有効にする」を押すと、Unity は会話を停止し、`nativeVoiceControl`／`control` の新しい会話 session を要求します。Bridge は `owner=gpt` と safety STOP を適用し、新しい BrainFrame が fresh STOP であること、live session と `voiceControlAvailable` を確認してから `resume` を受け付けます。その後 Unity は localhost Bridge motor TCP へ接続し、既存の BrainMotorSource／locomotion 経路へ渡します。

GPT は `FORWARD`、`TURN_R`、`TURN_L`、`FORWARD_R`、`FORWARD_L`、`STOP` の6 Actionを提案するだけです。実行は既存 Brain、raw 神経出力、decoder、motor 経路を通り、Unity や GPT が motor 値を直接生成しません。指示受付とBrain適用は別の状態です。現在の正式画面は両者の詳細なイベント履歴を表示しないため、会話字幕を実行完了や移動成功の証拠にしません。

TTL、stale 750 ms、epoch 更新、Brain／Bridge 切断では身体出力を停止し、無断再開しません。再開には「声で操作を有効にする」をもう一度押します。ミュートは音声だけを止め、身体停止は緊急停止です。会話の入力・返答時には非物理の色 pulse を表示できますが、神経由来の感情や身体反応とは扱いません。

## 設定と診断

「設定と診断」を開くと、マイクデバイス・音量の設定、Brain backend／ready、frame age、sequence、schema errorを確認できます。パネル内をスクロールすると表示ゲイン、文字指示、会話全文も表示します。入力RMS、実サンプルレート、返信バッファ、underrunは現在の正式UIには表示しません。言語・voice・persona・custom persona text を変更して「停止状態で設定を適用」を押します。設定変更は会話停止かつ output inhibited の状態でのみ受理され、次回の明示的な会話開始が必要です。ミュート、unmute、デバイス変更はマイク資源と収録だけを切り替え、返答再生は止めません。

Bridge の `conversationGeneration` が変わった場合、Unity は字幕、マイク、返信音声を破棄します。古い generation の音声を送信せず、`old_conversation_generation` を成功扱いにしません。Bridge WS が切断した場合も Unity は直ちに録音、再生を停止します。

マイクを使わない受信専用の確認は `Start-UnityConversation.cmd -flyConversationNoMicrophone` で起動します。この引数では起動時から録音を禁止し、ミュート解除操作でも録音しません。通常の利用では付けず、通常起動は `Start-UnityConversation.cmd` とします。

## 未受入れの段階

- 自動収録、ミュート／unmute、デバイス変更、返信再生中の同時送受信を含む Windows 実マイク＋実 API 10往復は未受入れです。
- 会話＋身体操作、6 Action 各3回、fresh STOP／resume／stale の身体 gate は未受入れです。
- 15分継続、実音声機器の抜差し、AECの評価は未受入れです。起動終了の回数・プロセス残留結果は検証記録を参照してください。
- 実マイク、AEC、割込み発話、認識精度、返答品質、神経妥当性、移動品質、Gameplay は今回の画面確認から判断しません。

旧 Web client を併用すると単一 control WS 契約に違反するため、Unity 会話版の確認中はブラウザ Player や一時 guard を接続しないでください。
