# Unity 映像配信の運用手順

経路は `Unity framebuffer → JPEG → HTTP publisher → aiortc → WebRTC video-only → browser` である。これはJPEG pipelineであり、`com.unity.webrtc` へのnative rewrite、音声、Brain操作、公開サーバー、TURNは対象外。Scene変更は不要で、設定が有効な環境だけが配信する。

## 起動

リポジトリルートで Python 3.10 以上を使う。

```sh
python3 -m venv .venv-video
.venv-video/bin/python -m pip install -r Runtime/Video/requirements.txt
.venv-video/bin/python tools/video.py init --stream unity-mac
.venv-video/bin/python tools/video.py doctor
.venv-video/bin/python tools/video.py up --config Runtime/Video/local/backend.json --metrics-output artifacts/video-up.jsonl
```

`up` は backend を foreground で起動し、`--player <実行ファイルまたは.app>` と `--publisher-config <publisher.json>` を同じ supervisor で起動できる。`--ssh-target user@host` は、remote backendが既に起動している場合に同じportのSSH forwardだけを監督し、remote processを起動・停止・制御しない。`status` は読み取り専用、`up` は自分が起動した子だけを追跡する。終了は Ctrl-C または SIGTERM で、所有した process groupだけを停止する。既存portのprocessを採用・killしない。
```sh
.venv-video/bin/python tools/video.py status --config Runtime/Video/local/backend.json
```

`status` の結果は `{mode,backendReachable,health,unityPlayerValidated:false}` で、5キー（`service`、`instanceId`、`uptimeSeconds`、`viewers`、`streams`）は nested `health` object にある。`streams` の各status objectで `waiting/live/stale`、sequence、frameAge、publisher/source、metricsを確認する。healthが別instanceIdなら、別backendを見ているためready扱いしない。

Mac Playerの実行例は `.venv-video/bin/python tools/video.py up --config Runtime/Video/local/backend.json --player /path/to/Fly.app --publisher-config Runtime/Video/local/publisher.json`。Windowsでは `py -3 -m venv .venv-video` の後、`.venv-video\Scripts\python.exe -m pip install -r Runtime\Video\requirements.txt` で同じ依存関係を用意し、`.venv-video\Scripts\python.exe tools\video.py up --config Runtime\Video\local\backend.json --player C:\Games\Fly.exe --publisher-config Runtime\Video\local\publisher.json` を使用する（Windowsでの実行は未検証）。

Windows PowerShellでも同じ設計だが、今回の作業ではWindows standaloneの実行とWindows→Mac実接続は意図的にout of scopeである。過去のWindowsコマンドを現行の実証とはみなさない。

## 設定とsecret

backendは `Runtime/Video/local/backend.json`、publisherは `Runtime/Video/local/publisher.json` を使う。`init` は既存設定、token fileを上書きしない。Playerの設定優先順は `-flyVideoConfig`（絶対path）→ `FLY_VIDEO_CONFIG` → Editorのlocal publisher.json → PlayerのpersistentDataPath/fly-video.json。相対path、未存在、`enabled:false` は配信しない。

publish secretは `FLY_VIDEO_PUBLISH_TOKEN` → configの `tokenFile`（相対ならconfig同居）の順。backendとpublisherは同じtokenを使う。tokenとlocal JSONはGit管理外。portを変える場合はbackend、publisher、browser endpoint、SSH forwardの映像service portを揃える。`allowedOrigins` はUIの実際のorigin（例 `http://127.0.0.1:18771`）を許可する設定で、service portと同じである必要はない。
```sh
ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -L 8880:127.0.0.1:8880 user@mac-host
```

これはHTTP ingressだけを転送する。WebRTC UDPやLAN公開をSSHだけで成立させない。

## Unity publisher と telemetry

Sceneにcomponentを配置せず、enabled設定でbootstrapする。標準は960×540、15 fps、q75、`verticalFlip:"auto"`。`Application.runInBackground` は送信中だけ変更して停止時に戻す。`-nographics`、batchmode、非表示Game viewでは `WaitForEndOfFrame` の実映像を保証しない。

各uploadは `X-Publisher-Id`、単調な `X-Frame-Sequence`、source label/OS、任意の `X-Frame-Metadata` を送る。telemetryの `captureMs`、`encodeMs`、`uploadMs`、`gameFps`、`videoFps`、`jpegBytes`、`diagnosticsOverlay` と、BrainMotorSourceから得た `brainIdentity` を送る。game FPSは `Update` の秒区間から計算する。metadataはbase64 JSON decoded最大4096 bytes、identityの文字列は1..128 printable ASCII。serverのFPS上限は10000で、これを設定値15 fpsの保証と混同しない。

diagnostics overlayは既定falseで明示opt-inする。trueかつ実際の出力画像が256×8以上の場合のみencoded JPEGにmarkerを付ける。ゲームのRenderTextureやUIには書き込まない。probeは10秒stickyで、binding変更時にリセットする。markerの構造と測定の意味は [video-v1 protocol](../../Contracts/video-v1/protocol.md) に従う。

## Browser と identity gate

browserは config → video-only recvonly offer → answer → status の順で接続し、約500msでstatusを更新する。publisher切替、identity binding変更、stale、frame停止、peer failureでは旧映像を破棄して再接続する。

再接続は最大6回、待ち時間は500ms、1s、2s、4s、8s、8s。browserの初回frame timeoutは2秒、通常の受信frame timeoutも2秒。headless `video_measure.py` の初回frame timeoutだけは5秒。3秒間の新しい描画frame受信でretry countをリセットする。`FlyVideo` は `state()`、`measurements()`、`setExpectedIdentity()`、`disconnect()` を公開する。measurementsは最大600件でimmutable。期待IDは既存のUI/backend sessionから渡し、実際にactive controllerのBrainMotorSourceとraw status/frame aliveを観測できた場合だけ照合する。

一致条件は instance/session、利用可能なbackend/dataset/config/graph/source hash、`brainConnected=true`、UIが実際に観測したBrainFrame sequenceとの完全一致、identity freshness 750ms以内。recent cacheは最大128件で、同じframeの反復受信だけではfreshnessを延長しない。raw frameのmodeは実値（例 `MALECNS`）を記録し、literal `LIVE` を必須にしない。REPLAY/MOCKは実Brain経路の証拠にしない。欠落や証拠不足は `unknown` のまま、mismatchは `mismatch` とし映像を非表示にする。期待IDを渡していない単なるLIVEは、Brainとの一致を意味しない。

browserの `visualRoundTripMs` は同じperformance clockで「probe request → Unity次frame → display callback」を測る上限値で、request/publisher待ちを含む。片方向capture latencyやPC間時刻差ではない。`tools/video_measure.py` は browser不要のaiortc受信計測で、`visualRoundTripToDecodeMs` は decoded frame到着までの値であり、browser表示値の代替ではない。

## 30分計測と成果物

`tools/video_measure.py` はUnity/Brainを制御せず、status identity bindingを監視し、source変更時にpeerを閉じ、WebRTC `getStats()`、受信FPS、frame gap、process CPU/RSS、reconnect、downtime、probe nonceをJSONLへ記録する。CPU 100%は1 core相当。出力はGit管理外 `artifacts` 配下に置く。

```sh
.venv-video/bin/python tools/video_measure.py --endpoint http://127.0.0.1:8880 --stream unity-mac --duration 1800 --output artifacts/video-measure/run.jsonl --reconnect-every 300
```

`--reconnect-every` は任意で10秒以上。summaryは同名 `.summary.json`。出力が既にある場合は上書きしない。`maxFrameGapMs` は各接続中のdecode frame間隔で、再接続を挟む停止時間は `downtimeSeconds` で確認する。計画した再接続と予期しない失敗を分け、`headlessMetric`、sourceHashes、依存versionも併読する。

## 検証結果（2026-09-12）

Unity 6000.5.5f1で今回のC#をコンパイルし、compiler error 0・exit 0を確認した（`artifacts/video-ops-validation/compile.log`）。JavaScriptの構文確認とPlayer HTMLの再生成も成功している。

外部Chromeでは診断映像640×360・5 fpsを受信し、新frameの描画、publisher停止時の映像非表示、操作なしの自動復旧、明示切断後の停止維持を確認した。Brainとマイクは未接続。証拠は `artifacts/video-ops-validation/chrome-live.txt` / `chrome-live.png`、`chrome-paused.txt`、`chrome-recovered.txt`、`chrome-disconnected.txt` に保存している。

HTTPの認証・Origin・metadata検査、probe応答、二重起動の拒否、SIGTERM時の所有process解放も確認した。Unixの終了済み接続が残る場合の起動判定を修正し、修正後も既存listenerを拒否することを確認している。証拠は同フォルダの `http-summary.json`、`sigterm-summary.json`、`invalid-preflight-summary.json`、`endurance-occupied-summary.json` にある。

診断JPEG（640×360・5 fps）を2受信者で1800秒受信した。継続側は8,998 frame、300秒ごとに再接続する側は8,992 frame・計画再接続5回。予期しない失敗と観測されたRTP packet lossは両側0だった。各受信者のsummaryとraw JSONLは `artifacts/video-ops-validation/endurance-receiver-{steady,reconnect}.*` に保存している。

| 計測項目 | 結果 |
|---|---|
| backend CPU（1 core = 100%） | 中央値3.0%、最大4.5% |
| backend RSS | 最初60秒の中央値124.6 MB、最後60秒132.5 MB、最大180.6 MB |
| probe要求→decoded frame | 両受信者とも中央値約522 ms、p95約626 ms、各357 sample |

CPU/RSSは両受信者の稼働期間が重なる区間で集計した。RSSは再接続直後に増え、その後下がる区間があり、この30分だけで長期のリーク不存在は保証しない。probe時間は5 fpsのpublisher待ちを含む往復の値で、Unityの片方向E2EやChrome表示遅延ではない。

原1800秒記録の `downtimeSeconds` は計画再接続の停止時間を含まない。計測終了後にこのカウンタだけを修正し、原記録を保持したまま30秒・10秒ごとの計画再接続で再確認した。144 frame・計画再接続2回・その他の失敗0、停止時間1.102秒を記録した（`artifacts/video-ops-validation/reconnect-downtime-receiver.summary.json`）。各runのsource hashを保存している。Unityのゲーム動作やゲームFPSはこの診断試験に含めない。

新runtimeでのUnityゲーム負荷・実Brain照合・実Unity映像の長時間試験は未実施。[AGENTS.md](../../AGENTS.md)のWindows実BrainへLiveTcp接続する試験ルールに従い、MacのBrain未接続映像シーンを使う例外は承認待ちである。Windows単体・Windows→Macの実通信は今回の依頼から除外されている。公開配信、TURN、native Unity WebRTCへの移行も実施していない。

以前のMac MOCK sceneによる60 frame・向き補正・LIVE/STALEの記録（`artifacts/video-unity-final-validation.json`、`artifacts/video/browser-unity-live.png`）は当時の証拠として保持し、今回追加した機能の実測証拠とは区別する。
