# Video v1 protocol

この契約は Unity の最終画面を独立して browser へ届けるための loopback-only HTTP/WebRTC protocol である。Brain、Bridge、入力、motor、session 対応を含まない。backend は aiohttp、aiortc、Pillow を使い、Unity は JPEG を HTTP POST し、browser は video-only の WebRTC offer を送る。

## 固定条件と上限

- backend は既定 `http://127.0.0.1:8880`。request Host は `127.0.0.1:8880` または `localhost:8880`、remote は `127.0.0.1` または `::1` に限る。
- Origin がある場合、loopback の 8771、18771、4173、backend port の明示的な origin だけを許可する。任意の LAN origin は許可しない。
- `iceServers` の既定値は空配列。外部 STUN/TURN は設定しない。
- publisher lease は 5 秒、frame stale は 2 秒、backend の viewer 上限は既定 2、設定上限 4。
- frame は JPEG、幅16..1920、高さ16..1080、画素数最大1920x1080、HTTP body最大2 MiB。
- Unity の publisher 設定上限は幅 1920、高さ 1080、1..30 fps、JPEG quality 1..95。標準設定は 960x540、15 fps、q75。
- publisher は stream ごとに 1 枠で、同じ publisher の sequence は単調増加でなければならない。古い値は拒否する。

## 共通エラー

エラーは `{"error":"<stable-code>"}` の JSON。未知の内部情報、path、token、SDP は返さない。主な status/code は `403 loopback_only`、`403 origin_not_allowed`、`401 publisher_auth_required`、`403 native_publisher_required`、`404 unknown_stream`、`400 invalid_frame_metadata`、`415 jpeg_required`、`429 publisher_busy`、`409 publisher_slot_in_use`、`409 old_frame_sequence`、`400 invalid_jpeg`、`413 frame_too_large`、`408 frame_upload_timeout`、`409 publisher_not_live`、`429 viewer_limit`、`400 invalid_offer_or_ice_timeout` である。

## Endpoints

### `GET /api/video/config`

loopback browser が接続先を確認する。認証不要。response 例:

```json
{"iceServers":[],"streams":["unity-mac","unity-windows"],"staleAfterMs":2000}
```

### `GET /api/video/streams/{stream}`

stream の最新状態を返す。認証不要。`state` は `waiting`、`live`、`stale` のいずれか。`live` は最新 frame の受信から 2 秒未満、`stale` はそれ以上である。

```json
{"streamId":"unity-mac","state":"live","sequence":43,"frameAgeMs":120,
 "publisherId":"<8..64 alnum-or-hyphen>","source":{"kind":"unity-game","label":"unity-mac","executionOs":"macOS"},
 "width":960,"height":540,"viewers":1}
```

publisher がまだいなければsequenceは `-1`、publisherId/source/width/height/frameAgeMsはnull。viewersは現在のsession数である。source.kindはUnityなら `unity-game`、診断画像なら `diagnostic`。各metadataは認証済みpublisherの自己申告であり、Brain identityとの対応を保証しない。

### `POST /api/video/streams/{stream}/frames`

Unity native publisher 専用。Origin header は付けない。必須 headers は次の通り。

| Header | 契約 |
|---|---|
| `Authorization` | `Bearer <publish-token>`。32..256 ASCII token。環境変数が token file より優先。 |
| `Content-Type` | `image/jpeg` |
| `X-Publisher-Id` | ASCII英数字または `-`、8..64文字。起動ごとに新しい ID。 |
| `X-Frame-Sequence` | 0 以上の十進数、最大15桁。同一 publisher では前回より大きい値。 |
| `X-Execution-Os` | `macOS`、`Windows`、または protocol diagnostic の `diagnostic`。 |
| `X-Source-Label` | printable ASCII、最大80文字。 |

body は JPEG bytes。受理時は `200` と `{"acceptedSequence":43}`。stream が別 publisher に占有され、最後の受信から 5 秒未満なら 409。所有者が変わったときは既存 viewer session を閉じ、古い video を新しい source として継続しない。

### `POST /api/video/streams/{stream}/offer`

browser の認証不要 offer endpoint。stream が live で、viewer 上限未満でなければならない。request は `Content-Type: application/json`、body は次の二キーだけを持つ。

```json
{"type":"offer","sdp":"<SDP>"}
```

SDP は単一の `m=video` m-line、`a=recvonly`、最大 120000 文字。data channel、audio、sendrecv は受け付けない。body 上限は 128 KiB、SDP/ICE 処理 timeout は契約実装に従う。成功時 `200`:

```json
{"type":"answer","sdp":"<SDP>","sessionId":"<opaque id>"}
```

browser は answer を remote description に設定し、video track の接続状態を監視する。`com.unity.webrtc` は使わず、backend の aiortc が track を提供する。

### `DELETE /api/video/sessions/{session}`

browser の切断、pagehide、publisher 切替時の cleanup 用。認証不要。存在しない session でも `204` とし、再実行可能にする。

## 状態と freshness

`Stream` は履歴をキューにせず最新 JPEG frame だけを保持する。track は同じ frame を視聴者ごとに再フォーマットし、stale 後に過去 frame を送らない。publisher 切替では generation が変わり、既存 track は停止する。browser の LIVE は、WebRTC peer が connected、status が live、frame age が 2 秒以内、かつ browser が新しい video frame を描画した場合だけ成立する。

## 検証と未検証

`artifacts/video-protocol-validation.json` にsynthetic 2-peer/39-frame、auth、origin、sequence、競合、stale、cleanupを記録。Mac Player実映像960x540の60frame受信と、補正後のbrowser LIVE目視・停止時非表示を確認。詳細・証拠・未検証範囲は [運用手順](../../Docs/integration/Unity-WebRTC-Video.md) を参照。Windows実機、跨機実映像、音声は未検証。
