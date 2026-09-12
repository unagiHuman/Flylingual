# Video v1 protocol

Unity の最終画面を、loopback-only の JPEG ingress と aiortc WebRTC video track で browser に届ける契約である。Brain、Bridge、入力、motor、音声、native Unity WebRTC はこの契約に含めない。実装・運用の正本はこの文書と [Unity-WebRTC-Video.md](../../Docs/integration/Unity-WebRTC-Video.md) である。

## 境界と固定値

- backend は既定 `http://127.0.0.1:8880` に bind する。Host は `127.0.0.1:<port>` または `localhost:<port>`、remote は `127.0.0.1` / `::1` のみ許可する。Origin は設定済みの loopback origin のみ許可し、LAN 公開や TURN/STUN の導入はしない。
- 1 stream は最新 JPEG 1枚だけを保持する。frame stale は2秒、publisher lease は5秒、viewer上限は設定既定2・上限4。publisherまたはidentity bindingが変わったら generation を進め、古いpeerを閉じる。通常のframe sequence増加ではpeerを閉じない。identity bindingは frameAgeMs/frameSequence を除く7つの固定IDで比較する。
- JPEG は幅16..1920、高さ16..1080、最大1920×1080、HTTP body最大2 MiB。publisherの設定上限は30 fps、quality 1..95（標準960×540、15 fps、q75）。server metadata の FPS 値の上限は現在 `MAX_FPS=10000` である。
- 同一 publisher の `X-Frame-Sequence` は単調増加。publisher high-water は最大16 publisher分のbounded setで、backend再起動をまたいで永続化しない。

## Endpoint

`GET /api/video/config` は `{iceServers:[], streams:[...], staleAfterMs:2000}` を返す。

`GET /api/video/health` は次の5キーだけを必須とする health object を返す。

```json
{"service":"flylingual-video","instanceId":"<uuid>","uptimeSeconds":12.3,
 "viewers":1,"streams":[{"streamId":"unity-mac","state":"live","sequence":43,
 "frameAgeMs":120,"publisherId":"...","source":{},"width":960,"height":540,
 "viewers":1,"metrics":{}}]}
```

`GET /api/video/streams/{stream}` は同じ stream status object を返す。`state` は `waiting` / `live` / `stale`、未受信時 `sequence=-1`、publisher/source/寸法/age は null、`viewers` は現在のsession数である。`metrics` には `receivedFrames`、`receivedBytes`、`decodeMs`、`ingressFps`、`ingressKbps` と、publisher telemetry object を含む。

`POST /api/video/streams/{stream}/frames` は Unity/native publisher 専用で、Originを付けない。必須 header は次の通り。

| header | 制約 |
|---|---|
| `Authorization` | `Bearer <token>`。32..256 ASCII。環境変数が token file より優先。 |
| `Content-Type` | `image/jpeg` |
| `X-Publisher-Id` | ASCII英数字または `-`、8..64文字。起動ごとに新規。 |
| `X-Frame-Sequence` | 0以上の十進数、最大15桁。publisher内で増加。 |
| `X-Execution-Os` | `macOS`、`Windows`、または診断用 `diagnostic`。 |
| `X-Source-Label` | printable ASCII、最大80文字。 |
| `X-Frame-Metadata` | 任意。後述の base64 JSON。 |

成功時は `200 {"acceptedSequence":43,"probeNonce":0}`。別publisherが lease 内に存在すれば409、古いsequenceは409。bodyはJPEGでなければならず、認証・Origin・サイズ・sequence違反の詳細を漏らさない。

`POST /api/video/streams/{stream}/offer` は認証不要の video-only `recvonly` offer。SDP bodyは `type` と `sdp` の2キーだけ、単一 `m=video`、最大120000文字、data channel/audio/sendrecvは禁止。成功 response は `type:"answer"`、`sdp`、`sessionId`、現在の `publisherId` と `source`。`DELETE /api/video/sessions/{session}` は冪等なcleanupである。

## Frame metadata と identity

`X-Frame-Metadata` は base64(JSON UTF-8)、decoded最大4096 bytes。既知の publisher key は `captureMs`、`encodeMs`、`uploadMs`（前回upload requestの時間）、`gameFps`、`videoFps`、`jpegBytes`、`diagnosticsOverlay`、`brainIdentity`。未知のkeyは400とする。時間値の最大は600000、FPSの最大は10000、`jpegBytes` は整数かつ最大2 MiB。`diagnosticsOverlay` はbooleanである。

`brainIdentity` は次の全9 keyを必須とする。

`instanceId`、`sessionId`、`backendId`、`datasetId`、`configHash`、`graphHash`、`sourceHash` は1..128文字の printable ASCII。`frameAgeMs` は0..86400000、`frameSequence` は0..2147483647の整数。identityはpublisherの自己申告であり、それだけでは実Brainの同一性を証明しない。実際に固有な active controller の BrainMotorSource と、観測されたraw status/frame alive を併記できる場合だけ証拠として扱う。raw frame の mode はプロジェクトの実値（例 `MALECNS`）を記録し、literal `LIVE` を要求しない。REPLAY/MOCKは実Brain経路の証拠にしない。

browser側は `FlyVideo.setExpectedIdentity(value)` に UI が期待するIDと最新の `frameAgeMs` / `frameSequence` を渡す。`FlyVideo.state()` は凍結された現在状態、`FlyVideo.measurements()` は最大600件の凍結測定履歴を返す。UIが実際に観測した BrainFrame sequence の bounded recent cache（最大128）から、同じ sequence を observed identity と照合する。反復した同一frameの受信だけでは freshness を更新しない。expected/observed双方で instanceId、sessionId、backendId、datasetId、configHash、graphHash、sourceHash の7 ID/hashを全て必須とし、brainConnected=true、正確に同じ frameSequence、freshness 750ms以内が揃って初めて `identityState:"matched"` とする。欠落は `unknown`、既知の不一致は `mismatch` とし、mismatch時は映像を表示しない。
## 診断 overlay と probe

diagnostics overlay は既定falseのopt-inで、256×8のmarkerをencoded videoにだけ重ねる。UIを変えるものではない。overlay時は server の `POST /api/video/streams/{stream}/probe` に `{"nonce":<uint32>}` を送れる（nonceは1..4294967295）。responseは `acceptedSequence` と `probeNonce`。serverは受理後10秒間、bindingが変わるまでnonceをstickyにし、次のupload responseにも `probeNonce` を返す。publisherが変わる、identity bindingが変わる、overlayがfalseになるとリセットする。

markerは64 bits、4×8 pixel blocksで、`magic 16 bits = 0xD3A5`、`nonce 32 bits`、`checksum 16 bits = high16(nonce) XOR low16(nonce) XOR 0x6B4D`。画像の上端または下端でdecodeする。browserの `visualRoundTripMs` は probe request → Unityの次のframe → browser display callback を同じ `performance.now()` で測る上限値であり、publisher待ちを含むが実際の片方向capture latencyではない。headless `tools/video_measure.py` の `visualRoundTripToDecodeMs` は decoded aiortc frame到着で終了し、browser表示ではない。PC間のwall-clock減算をしない。

## 状態遷移・エラー・証拠

publisher/source/identity bindingの変更、stale、peer failureは古いtrackを閉じ、browserは映像を隠して再接続する。通常のsequence増加は継続送信である。Brainが一時停止して frameAgeMs が増えても、publisher bindingが同じなら映像を直ちに閉じない。receiver側の750ms freshness判定は identity を unknown にする。実client disconnect、mode変更、binding不明化は source/identity を無効化し映像を閉じる。主な安定errorは `loopback_only`、`origin_not_allowed`、`publisher_auth_required`、`native_publisher_required`、`unknown_stream`、`invalid_frame_metadata`、`jpeg_required`、`publisher_busy`、`publisher_slot_in_use`、`old_frame_sequence`、`invalid_jpeg`、`frame_too_large`、`frame_upload_timeout`、`publisher_not_live`、`viewer_limit`、`invalid_offer_or_ice_timeout`、`diagnostics_overlay_required` である。

旧 `artifacts/video-protocol-validation.json` と旧Macの実映像記録は、当時のsynthetic/auth/origin/sequence/stale/cleanupおよびMac MOCK sceneの証拠として保持する。これは今回の新runtime検証、Brain identity matching、Windows実機、Windows→Mac跨機、長時間計測の合格証拠ではない。新しい検証は成果物JSONLとsummaryを根拠にし、未実施・未観測を成功扱いしない。
