# Unity ネイティブ会話版の利用手順

これは Unity が会話 UI、マイク、返答音声、字幕、診断表示を担当する初版です。Unity Windows Player、同居 Bridge、同居 Brain は Windows 内で動作しますが、GPT Live と Responses は Bridge から外部 OpenAI API へ接続するため、Windows の外向きネットワークが必要です。

## 対象範囲

初版は段階 1〜3の **会話のみ** モードです。`chat_only` では行動要求を Bridge 側で拒否し、身体出力は抑止します。実装と自動検証の結果は [検証記録](Unity-Native-Conversation-Validation.md) に記録します。実マイク10往復、6 Action の各3回、15分継続、身体移動、Gameplay acceptance は未受入れです。`ready=false` と750msの制限は維持します。

会話の責務は「音声・字幕・会話状態」、Brain／Bridge の責務は「外部 API、意図翻訳、Brain 接続、排他、安全停止」です。Unity は Brain TCP や API へ直接接続せず、Bridge の control/audio WS だけを使います。旧ブラウザ Player や WebRTC はこの会話版に不要で、同じ Bridge へ第二の control WS を開かないでください。

## 初回準備

Unity Player の対象ファイルは次です。

`artifacts/windows-native-conversation/unity/FlylingualConversation.exe`

秘密鍵の本文は表示・コピーせず、Git 除外の local 設定にファイルパスだけを書きます。

```powershell
Copy-Item Runtime/Config/windows-native.example.json Runtime/Config/windows-native.local.json
notepad Runtime/Config/windows-native.local.json
```

`bridgePython` は `.venv-bridge/Scripts/python.exe`、`bridgeLocalConfig` は `Runtime/Config/local.json`、`keyFile` は実際の外部キー1行ファイルにします。既存の local 設定を使う場合は `windows-stack.local.json` も受け付けます。

Bridge 環境に process ownership 用依存を入れます。

```powershell
uv pip install --python .venv-bridge/Scripts/python.exe -r tools/requirements-windows-native.txt
```

ヘッドセットを推奨します。初版は PTT（押して話す）で、Unity の Windows `Microphone` API を使います。ブラウザの AEC／noise suppression が自動的に得られる構成ではないため、スピーカー同時通話や割込み発話は後段です。

## 起動と終了

次を実行します。

```powershell
.\Start-UnityConversation.cmd
```

必要な場合は Player 引数を追加できます。

```powershell
.\Start-UnityConversation.cmd -screen-width 1280 -screen-height 720
```

`-flyConversation` により `ConversationNativeBootstrap` が Unity の所有者 PID と heartbeat を作り、`tools/windows_native.py` を起動します。helper は `windows-local`、Bridge の `Runtime/Config/local.json`、秘密鍵パスを使い、Brain／Bridge を自分が起動した子だけ管理します。既存ポートを無条件に奪ったり、一括 kill したりしません。Unity を閉じると stop marker が書かれ、Bridge の会話終了と所有子プロセスの停止が行われます。

専用exeの直接起動でも同じ会話モードになります。内部サービス起動とローカル制御WS接続は自動で行い、画面の接続状態が `connected` になったら「会話を開始」を押します。起動しただけではGPT会話やマイク送信を開始しません。

## 会話操作

1. 「会話を開始」を押します。Bridge へ `conversation_start` と `interaction: chat_only` を送り、会話世代を確認します。会話のみでは owner は observer のままで、`resume` や Action は送信しません。
2. Spaceキーか「押して話す」ボタンを押し続けて話します。最初のPTTでマイク収録を開始し、離すと送信を止めて未送信データを破棄します。会話終了でマイクを解放します。返答再生中と終了後200msは送信を抑止します。
3. 返答音声は Unity の AudioSource で再生し、返答と自分の認識結果を字幕に表示します。再生中は入力を抑止し、古い世代の音声・字幕は破棄します。
4. 「会話を終了」を押すと PTT、マイク、再生キュー、会話セッションを終了します。
5. 「身体を停止」は緊急停止です。会話を終了し、Bridge に safety STOP を要求します。

## 設定と診断

「設定と診断」を開くと、マイクデバイス、入力 RMS、実サンプルレート、返信バッファ、underrun、音声エラー、Bridge の backend、Brain ready、frame age、sequence、schema error を確認できます。言語・voice・persona・custom persona text を変更して「停止状態で設定を適用」を押します。設定変更は会話停止かつ output inhibited の状態でのみ受理され、次回の明示的な会話開始が必要です。

Bridge の `conversationGeneration` が変わった場合、Unity は字幕、マイク、返信音声を破棄します。古い generation の音声を送信せず、`old_conversation_generation` を成功扱いにしません。Bridge WS が切断した場合も Unity は直ちに PTT、録音、再生を停止します。

## 未受入れの段階

- 段階3の Windows 実マイク＋実 API 10往復は未受入れです。
- 会話＋身体操作、6 Action 各3回、fresh STOP／resume／stale の身体 gate は未受入れです。
- 15分継続、実音声機器の抜差し、AECの評価は未受入れです。起動終了の回数・プロセス残留結果は検証記録を参照してください。
- 実マイク、スピーカー AEC、認識精度、返答品質、神経妥当性、移動品質、Gameplay はこの初版から判断しません。

旧 Web client を併用すると単一 control WS 契約に違反するため、Unity 会話版の確認中はブラウザ Player や一時 guard を接続しないでください。
