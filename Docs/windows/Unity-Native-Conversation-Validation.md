# Unityネイティブ会話初版：実装・自動検証

2026-09-12。main `a9c15a1` からの作業ツリーで実装・ビルド。
ユーザーの追加指示により、今回はビルドと自動検証まで実施した。
実マイクでの10往復を実施したという記録ではない。

## 実装した範囲

- Windows専用 `FlylingualConversation.exe`。直接起動または `Start-UnityConversation.cmd` から起動。
- Unityの日本語画面、マイク選択、PTT、24kHz PCM変換、返答再生、字幕、設定、診断、停止。
- Unityが同居Python Bridge/実Brainを非表示起動し、終了時にAPIセッションと自己所有プロセスを解放。
- `conversation_only_v1` / `chat_only`。音声の世代を身体epochから分離し、Bridgeが行動要求を拒否。
- ネイティブ会話版ではReplayを選択・ロードせず、身体motor sourceを抑止、ゲーム進行を停止。
- WebRTC、Videoサービス、ブラウザは通常起動に不要。旧実装とMac profileは維持。

会話＋行動、6 ActionのネイティブUI、自動音声検出、AEC、配布用Python同梱は後段。
初版のBrain観測は画面診断に限定し、GPT音声へ現在の観測として渡さない。

## 確認結果

| 検証 | 結果と範囲 |
|---|---|
| Unity 6000.5.5f1 Windowsビルド | 成功。専用defineでexe直接起動も会話モード |
| 純粋PCM EditModeテスト | 4/4。ステレオ48kHz、途中破棄、96kHz短片、出力補間位相 |
| Python契約・起動管理テスト | 20/20。行動拒否、旧世代拒否、停止競合、所有PID、旧launcher回帰など |
| Editorの実Brain接続 | 1/1。専用Sceneでsequence進行、出力抑止、Play Mode終了後stopped確認。API未使用 |
| 最終Playerの連続起動・終了 | 5/5。各回で実API live、字幕delta、非ゼロPCM、音声callback進行、停止後バッファ0 |
| 二重の制御WebSocket | 5/5、HTTP 409で拒否 |
| 所有プロセス残留 | 全5回で0。終了後18766/18770/18771/8880のlistenerなし |
| 実画面 | 保存したPlayer画像で日本語UI・3D表示を確認。音声多重配置警告は修正済み |

PlayerのAPI試験は、短い挨拶の返答先頭を受信・再生処理し、途中停止する試験。
各回4,800 bytesの非ゼロPCMを受信、音声callbackは1,024〜4,096 output samples進行した。
マイク送信は0。実際のスピーカー音を人が聞いたこと、完全な発話の品質、会話10往復とは区別する。
マイクデバイスは3件列挙されたが、収録は開始していない。

## 実Brainと資源の証拠

- 接続先: Windows実Brain `127.0.0.1:18766`、Bridge制御 `127.0.0.1:18771`。
- backend `MALECNS_EXPERIMENTAL`、dataset `male-cns:v1.0`、mode `LIVE`、受信readyは全てfalse。
- 最終5回のBridgeログには実BrainFrame 60件。各Playerでsequence進行を確認。
- 各sessionの `controller_release` は `activeControllerCount=0`。単なるポート空きと区別して保存。
- 起動〜終了・解放確認のwall time: 中央値14.610秒、最大17.563秒（N=5）。会話応答遅延ではない。
- 同時に監視したプロセスツリーのピークRSS合計: 977,588,224 bytes。長時間リーク試験ではない。
- Python 3.10.12、aiohttp 3.14.3、psutil 7.2.2。Brain source/config/graph hashと各frameのperformanceは証拠JSONに保存。

## ローカル成果物

- Player: `artifacts/windows-native-conversation/unity/FlylingualConversation.exe`
- 最終5回: `artifacts/windows-native-conversation/validation-20260912-224545/summary.json`
- identity/hash/frame/RSS/解放: 同ディレクトリの `evidence.json`
- 画面・Playerログ: 同ディレクトリの `cycle-1.png`〜`cycle-5.png`、`player-1.log`〜`player-5.log`
- Editor結果: `artifacts/windows-native-conversation/editor-live-tests.xml`
- PCM結果: `artifacts/windows-native-conversation/pcm-tests.xml`
- ビルド: `artifacts/windows-native-conversation/build.log`

生成物・キー・端末設定はGit対象外。コードと定義変更には、Bridge契約、共通設計、
UnityのAudio/GUI module依存、ネイティブ起動設定例を含む。build時に発生した既存URP assetの
自動書換えは作業差分から除いた。既存のBrainモデル・decoder・CPG・PhysX設定は変更していない。

## 再実行

リポジトリ直下から実行。Unity/Brain/制御WSは同時に一つの検証担当だけが所有する。

```powershell
.\.venv-bridge\Scripts\python.exe -m unittest tools.test_native_conversation tools.test_windows_native tools.test_windows_local
unity test UnityProject --editor-version 6000.5.5f1 --mode EditMode --filter Flylingual.Conversation.EditorTests
unity test UnityProject --editor-version 6000.5.5f1 --mode EditMode --filter NativeEditorIntegrationTests.EditorConnectsToRealBrainAndReleasesOwnedServices
unity build UnityProject --editor-version 6000.5.5f1 --target StandaloneWindows64 --execute-method NativeConversationBuilder.Build
.\.venv-bridge\Scripts\python.exe tools/verify_native_player.py --cycles 5
```

最後のコマンドはWindows実Brainと実GPT APIを使用する。`-flyConversationProbe` は明示的な
開発用試験引数で、通常起動では会話・API・マイクを自動開始しない。

未確認: 実マイク10往復、音声機器抜差し・使用拒否の実機試験、15分継続、
会話＋行動の6 Action各3回、認識精度・音声聴取・身体動作品質。
これらを合格扱いにせず、次の受入れ段階として残す。
