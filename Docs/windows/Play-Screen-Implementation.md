# プレイ画面 実装申し送り

更新日：2026-09-13（JST）

## 実装範囲

正式シーンで起動する `PlayScreenRuntime` と `PlayScreenView` が、既存のゲームカメラをRenderTextureへ描画し、UI Toolkitで3領域を構成する。左のゲーム映像が7、右側が3の幅比で、右側には「脳・神経活動」と「ハエリンガル」を上下に配置する。ゲーム映像は16:9の1600×900 RenderTextureを `ScaleToFit` で表示し、切り抜き・縦横の引き伸ばしを行わない。

正式な通常起動はリポジトリ直下の `Start-UnityConversation.cmd`。Player・Editorとも正式シーン `Assets/RuntimeIntegration/PlayScreen/FlylingualPlay.unity` を使う。既存の `FlyGroundedRealismDemo.unity` を元に、元シーンを変更せず生成した。ネイティブ起動BootstrapのEditor opt-inでも同じローカル構成へ接続する。

脳活動は `Resources/BrainVisualization/malecns-atlas.json` の実atlas（24,000ニューロン、細胞体座標）を使う。UIは既存の単一Bridge control WebSocketから受信した `brain_frame` を会話コントローラの観測イベント経由で受動購読する。表示のための追加Brain接続、control WebSocket、motor経路はない。backend、mode、sequence、windowMs、観測数、spike数、frame ageを表示し、ready=falseはそのまま示す。dataset、instance、sessionは受信検証に使用する。

脳観測の更新は既存の安全境界に従う。stale、切断、identity／atlas不一致、重複・逆順frame、壊れたpayloadでは活動を消去する。表示都合で750ms freshness制限を延長しない。

ハエリンガルは `FlyPortraitElement` のコード描画で、会話状態に応じて「待機」「聞いています」「発話中」「ミュート」を表現する。これは会話状態のキャラクター表現であり、脳活動から「うれしい」「怖い」などの感情を推定する機能ではない。活動値を感情へ直接変換しない。

設定と診断、字幕、会話再開・終了、身体停止、マイク、声で操作を有効化する既存UIを同じ画面へ配置した。正式ネイティブモードは既存の `WindowsReplayDemo.Awake` により `AscentGameSession` を無効にし、旧キーボード・カメラ入力を実行しない。脳表示のorbit／zoomは表示領域で処理する。

## 実表示確認

Unity Editor 6000.5.9で次を確認した。

- control接続：connected
- 会話：Ready=true
- BrainReady：falseを維持
- backend：`MALECNS_EXPERIMENTAL`
- mode：`LIVE`
- sequence：78から277へ進行
- atlas観測数：24,000
- 観測窓：50ms
- サンプル上のspikes：0
- 時折 `STALE` 状態を表示

Editor確認に続き、Windows Playerでも以下を確認した。移動品質や長時間安定性の検証とは区別する。

## Windows Player検証結果

Unity 6000.5.9f1／Windows x64 Development Buildが成功。通常ランチャーからWindowsローカル構成を起動し、実Brain `127.0.0.1:18766` → Bridge → 既存control WebSocketの受信で検証した。マイク取り込みは `-flyConversationNoMicrophone` で停止し、motor指示は送っていない。

| 項目 | 1920×1080 | 1280×720（最終ビルド） |
|---|---:|---:|
| 観測母数 | 約15秒／60サンプル | 約15秒／60サンプル |
| freshサンプル | 59（初期接続待ち1） | 60 |
| 有効sequence | 6 → 147 | 9 → 150 |
| freshサンプルの最大受信age | 119.379ms | 132.020ms |
| backend／mode | MALECNS_EXPERIMENTAL／LIVE | 同左 |
| Brain ready | 全サンプルfalse | 全サンプルfalse |
| 有効な観測細胞数 | 24,000 | 24,000 |
| 受信した発火数 | 0 | 0 |
| エラー報告 | 0 | 0 |
| ゲーム・神経Texture／停止ボタン表示 | 確認 | 確認 |
| 設定パネル開閉 | 確認 | 確認 |

画面PNGを目視し、3領域、日本語、字幕、主要ボタン、設定ドロワーの表示を確認した。設定開閉はpresentation-only probeから実行した。入力デバイス・人格の変更送信や音声による身体操作は本試験に含めない。1920×1080確認後の最終変更は、設定ドロワーの不透明背景と入力欄の配色であり、最終720pで再確認した。

最初のPlayer試行では動的PanelSettingsだけではICUデータが含まれず文字描画エラーとなった。`Resources/PlayScreenPanelSettings.asset` をUnity Editor APIで作成し、その複製を使う修正後、両解像度のログにICU／Exceptionエラーはない。終了時にはUnityのMemoryLeaks集計行が残るため、長時間メモリ安定性の合格とはしない。

証拠はリポジトリ内のGit除外領域に保存した。

- `artifacts/play-screen-1080p-final/`：report.json、play-screen.png、settings.png。
- `artifacts/play-screen-720p-final/`：同上、最終ビルド。
- `artifacts/play-screen-player-1080p-final.log`、`artifacts/play-screen-player-720p-final.log`。
- `artifacts/play-screen-source-evidence.json`：source HEAD、Brainソース・config・実atlas・原データのSHA256。ワークツリーには別タスクのBrain変更もあるためHEADだけを実行ソースとみなさない。

再ビルドはUnityメニュー `Flylingual > Play Screen > Build Windows Player`。出力先は `artifacts/windows-native-conversation/unity/FlylingualConversation.exe`。

検証コマンド（リポジトリ直下、出力パスは絶対パス推奨）：

```powershell
.\Start-UnityConversation.cmd -flyConversationNoMicrophone -screen-width 1280 -screen-height 720 -playScreenProbe C:/Users/tiger/UnityProj/Fly/FlyTest/Flylingual/artifacts/play-screen-720p-final -playScreenProbeQuit -logFile C:/Users/tiger/UnityProj/Fly/FlyTest/Flylingual/artifacts/play-screen-player-720p-final.log
```

probe指定がない通常起動では、自動終了・キャプチャは行わない。

## 依存・生成物

既存のENABLE_INPUT_SYSTEM設定でPipelineパッケージが参照するInput System依存が欠落していたため追加した。Unityが依存解決時に自動更新した版は1.20.0、URPは17.5.0。指定されていた6000.5.5は端末に未導入、6000.5.7は参照アセンブリ欠落のため使用できず、導入済みの正常なEditor 6000.5.9f1で検証・ビルドした。ProjectVersion、PackageManager設定、URP設定の自動移行を含む。

atlasの生成元は `Brain/MaleCNS/export_visualization_atlas.py`、出力はGit除外の `artifacts/play-screen-data/malecns-atlas.json`。実行時のUnity Resources配置は端末固有設定として管理し、APIキーやローカルパスを追跡ファイルへ保存しない。

公式MaleCNS v1.0細胞体注釈から生成したatlasIdは `0ceadfb2e5c3b07e57302cc3cd1f2e16661f1d2f3596199da5ddabc23eb7ec01`。graph 166,700、座標を持つ対象139,662から24,000を選択し、必須対象の欠測は0。原注釈SHA256は `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2`。接続線・シナプス個別の活動を描くものではない。

Bridge起動設定 `brain.visualizationAtlas` を省略時nullの任意項目として追加し、tools/dev.pyが既存の `--visualization-atlas` 引数へ渡す。本端末のGit除外 `Runtime/Config/local.json` にUnity Resources内の実atlasパスを設定済み。設定ローダーは有効パス、未指定、存在しないパスの拒否を確認済み。

## 未完了

非ゼロ発火の実測による発光確認は [Neural Glow 検証記録](Neural-Glow-Validation-20260913.md) の before-01 で別途確認した。意図的な切断・再接続、音声入力・身体操作、全設定項目の実操作、長時間負荷は未受入れである。この節の初期実Brain試験では有効spike payloadが0であり、活動を捏造して補っていない。RSS、Brain計算時間、刺激から身体までのE2Eは本表示試験で測定していない。感情推定の判定規則と対応する観測根拠も未確定であり、ハエリンガルは会話状態の表現まで実装した。

添付参照図は今回の閲覧で全面黒く表示され、位置、面積比、配色、文字を判別できなかった。そのため現在の7／3レイアウトとポンチ絵の表現は、実装確認できたUIと既存要件から定めたものであり、添付図を正確に転記したものではない。
