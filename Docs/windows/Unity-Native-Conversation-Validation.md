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
開発用試験引数。下記ハンズフリー修正以後は通常起動でも会話・API・マイクを自動開始する。
マイクを収録しない検証には `--no-microphone` を付ける。

未確認: 実マイク10往復、音声機器抜差し・使用拒否の実機試験、15分継続、
会話＋行動の6 Action各3回、認識精度・音声聴取・身体動作品質。
これらを合格扱いにせず、次の受入れ段階として残す。

## ハンズフリーと音声破棄の修正（2026-09-12 23:08 JST）

以下は半二重版の当時の実測。最新のマイク方針は末尾の「常時送信への変更」を参照する。

ユーザー依頼によりPTTを撤廃し、Bridge準備後に一度だけ会話を自動開始する。
既存の `pttHeld` 中に受信返信を捨てる処理と、PTT開始時の返信キュー消去を削除した。
入力許可と返答再生を分離し、マイクのミュートで返答を止めない。
通常起動ではマイクを自動収録し、非ゼロ返信再生中と終了後200msは入力を破棄、以後送信を再開する。
停止・切断後の自動再開はしない。身体出力は引き続き抑止する。

- Windows Playerビルド成功。ログ: `artifacts/windows-native-conversation/handsfree-build.log`。
- 既存PCM EditModeテスト4件成功: `artifacts/windows-native-conversation/handsfree-pcm-tests.xml`。
- 実行: `.\.venv-bridge\Scripts\python.exe tools/verify_native_player.py --cycles 1 --no-microphone`。
- Windows実Brain `127.0.0.1:18766`、Bridge `127.0.0.1:18771`、GPT Live実APIで1回成功。
- ボタン操作なしの会話開始、返答153,600 bytes受信、音量適用後の非ゼロ出力141,719 frames、字幕delta 11件。
  最初のパケットで停止せず、返信の継続再生まで確認した。物理スピーカーを人が聴取した証拠ではない。
- マイクは起動時から禁止し、送信チャンク0。入力再開・実マイク経由の往復は未検証。
  実マイクを自動収録・外部API送信する試験は自動承認レビューに拒否されたため、受信専用で実行した。
- Brain sequence 9、backend `MALECNS_EXPERIMENTAL`、ready=false、出力抑止=trueを維持。
- 停止3秒後に会話再開なし、音声バッファ0、所有プロセス残留なし、第二control WSは409。
  実Brainの同一sessionのcontroller解放は `activeControllerCount=0`。
- 終了処理中にBridgeの `background_failed: ClientConnectionResetError` が1件記録された。
  同時刻にcontroller解放とbridge_stoppedを確認。再生中のエラーや未解放とは区別し、終了時ログの扱いは残課題。
- 全体wall 16.797秒、プロセスツリーpeak RSS 980,590,592 bytes（N=1、応答遅延・長期安定性の指標ではない）。
- 原本: `artifacts/windows-native-conversation/validation-20260912-230832/summary.json` と `evidence.json`。
  evidenceには実行時source/config/graph hash、依存版、BrainFrameと解放イベントを保存した。

この修正では依存定義・Brainモデル・decoder・物理設定は変更していない。
マイクデバイス切替、実機音声出力、音声認識、10往復、15分連続の受入れは未完了。

## 常時送信への変更（2026-09-12）

ユーザーの訂正に従い、返信再生中および終了後200msのマイク送信抑止を撤廃した。
会話がliveの間はマイク入力と返答再生を同時に継続する。明示ミュート、会話終了、
切断、世代変更等の停止処理は維持する。受信音声が入力を止める処理はない。
GPT Liveの公式WebSocket例も入力を連続送信し、出力を別途受信・再生する構成である。
参照: https://developers.openai.com/api/docs/guides/voice-websockets

検証probeに返信再生中の送信チャンク数を追加し、マイク有効時の合格条件を同時送受信へ変更した。
この版の実マイク／実APIによる同時送受信試験は未実施。上の受信専用試験をその証拠にしない。
Windows Playerの再ビルドは成功（Unity CLI exit 0）。ログは
`artifacts/windows-native-conversation/duplex-build.log`。静的差分検査も成功。
AECは実装していない。依存定義、Bridge、Brain、物理設定はこの変更では変更していない。

## 声による操作経路と表示リアクション（2026-09-12 23:42 JST）

実装: 明示的な「声で操作」を追加。会話を停止してnative control sessionを開始し、
Bridgeのgpt owner、安全STOP、新鮮なSTOP適用frame、live会話を確認してresumeする。
以後GPT Live delegation→既存Responses意図解析→実Brain→既存raw decoder→
Bridge motor TCP→Unity BrainMotorSource/locomotionへ接続する。
声・返答への色pulseは見た目だけの演出で、脳の感情やmotorを捏造しない。

追加契約は `native_voice_actions_v1`、`nativeVoiceControl`、`conversationStopping`、
loopback `motorEndpoint` とnative音声の世代検証。Unityは身体用TCPでもsession/instance、
新規sequence、750ms、有限motorを照合し、制御断・失鮮度時に独立停止する。
旧chat_onlyとbrowser controlは保持し、依存定義・Brainモデル・decoder・PhysX設定は変更していない。

検証結果:

- Unity Windows Playerビルド成功: `artifacts/windows-native-conversation/actions-build.log`。
- Python契約／起動テスト22件成功:
  `.\.venv-bridge\Scripts\python.exe -m unittest tools.test_native_conversation tools.test_windows_native tools.test_windows_local`。
- 実動作試験コマンド:
  `.\.venv-bridge\Scripts\python.exe tools/verify_native_player.py --cycles 1 --no-microphone --actions`。
  マイク収録は起動時から禁止。文字を同じ意図解析へ送り、ASR／実音声経路を検証したとは扱わない。
- 初回 `validation-20260912-233627` はReactionのMaterialPropertyBlockをfield initializerで
  作成したUnity例外と身体ガード停止で不合格。Awakeで作成するよう修正した。
- 二回目 `validation-20260912-234002` は例外0だが身体ガード停止で不合格。
  新規frameの後も前frameのserver ageが残る問題を修正し、停止時の鮮度数値を追加した。
- 最終 `validation-20260912-234219` は例外0、会話切替→fresh STOP→resume→
  Bridge motor TCP→実frameから身体を有効化するところまで到達したが、**動作gateは不合格**。
  Brain frame 3→4が766ms間隔、frame 4のstepWallTimeMs=756.10msで750ms制限を超えた。
  UnityはframeAge=747.1ms、serverAge=768.9msで停止。制限を緩めず、無断再開しない。
- 最終trialのBrainFrame 10件、step wall最小510.05ms／最大756.10ms／平均619.82ms。
  6 Action各3回のうち最初のSTOP評価中に停止し、指示適用・移動の合格数は0。
  初期の身体位置変化約0.00052mは静止姿勢の変化であり、音声移動成功とはしない。
- backend `MALECNS_EXPERIMENTAL`、ready=false。最終wall13.547秒、peak tree RSS909,193,216 bytes。
  最後に会話停止・バッファ0・所有process残留なし・controller解放activeControllerCount=0。
  第二control WSは409。意図的TCP切断試験は、先に失鮮度で停止したため未達。
- 原本: `artifacts/windows-native-conversation/validation-20260912-234219/summary.json`、
  `evidence.json`、`player-1.log`。evidenceにsource/config/graph hash、依存版、frameと解放を保存。

残課題は実Brainの処理時間と余裕の確保、6 Action各3回、実マイクの指示・割込み、
移動・旋回品質、意図的切断、15分継続。現在のコードで50ms windowを500回のsim.step(1)に
分けていることは確認したが、神経計算をこのUI統合作業で変更してはいない。
性能改善には数値出力を維持する個別計測と再検証が必要である。
