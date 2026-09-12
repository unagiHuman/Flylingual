# Unity 映像配信の運用手順

この機能は、Unity の最終 framebuffer を独立したローカル映像としてブラウザへ表示する。Brain、Bridge、ゲーム入力、motor 制御、session 対応は扱わない。既存 Scene の変更は不要で、設定ファイルを置いた環境だけが配信する。

## 経路と制約

経路は次の通りである。

`Unity 最終 framebuffer → JPEG（既定 960x540 / 15 fps / q75）→ HTTP（localhost または SSH port forward）→ aiortc → WebRTC → browser`

これは pure end-to-end WebRTC ではない。Unity から backend までは HTTP JPEG ingress であり、backend が aiortc で WebRTC の video track に変換する。JPEG の中間生成と CPU encode がある。音声は対象外である。Unity の `UnityWebRequest` module を使い、`com.unity.webrtc` は使わない。

backend、Unity publisher、browser は既定で `127.0.0.1`/`localhost` に限定され、LAN 公開は未実装である。backend の既定 bind/port は `127.0.0.1:8880`。Origin は `http` の `127.0.0.1` / `localhost` と、8771、検証用18771、4173、backend自身のportの組合せだけが許可される。

## backend の起動（Mac / Windows 共通）

Python 3.10 以上を使う。リポジトリルートで次を実行する。Mac:

```sh
python3 -m venv .venv-video
.venv-video/bin/python -m pip install -r Runtime/Video/requirements.txt
.venv-video/bin/python tools/video.py init --stream unity-mac
.venv-video/bin/python tools/video.py doctor
.venv-video/bin/python tools/video.py serve
```

Windows PowerShell（venvのactivateやExecutionPolicy変更は不要）:

```powershell
py -3 -m venv .venv-video
.venv-video\Scripts\python.exe -m pip install -r Runtime/Video/requirements.txt
.venv-video\Scripts\python.exe tools/video.py init --stream unity-windows
.venv-video\Scripts\python.exe tools/video.py doctor
.venv-video\Scripts\python.exe tools/video.py serve
```

Windows で stream を選ぶ場合は `init --stream unity-windows` とする。`init` は既存の `Runtime/Video/local/backend.json`、`publisher.json`、`publish-token.txt` を上書きしない。`doctor` は設定と依存を検査し、`unityCaptureVerified` と `webRtcVerified` は実映像検証なしでは `false` のままである。`serve` は `http://127.0.0.1:8880` に bind する。

既存の local 設定を明示する場合は、両コマンドに `--config /絶対パス/Runtime/Video/local/backend.json` を付ける。backend 設定の `port` を 8880 以外にした場合、bind、Host 検査、allowedOrigins、publisher endpoint、browser endpoint、SSH forward のポートを全て一致させる必要がある。SSH の転送先だけを 18880 に変えて backend が 8880 のままだと、Host 検査で拒否されるため使用しない。まず同じ 8880 番を forward する。

## Unity Editor / Player の設定

Unity Editor は、リポジトリの `Runtime/Video/local/publisher.json` が存在し、`enabled: true` のとき、Play 開始後に bootstrap する。現在の雛形は `streamId: unity-mac`、endpoint `http://127.0.0.1:8880`、幅 960、高さ 540、15 fps、JPEG quality 75 である。Mac/Windows は `streamId` を `unity-mac` / `unity-windows` に切り替えて同じ backend の別 stream を選ぶ。Scene に publisher component を配置する必要はない。

`verticalFlip: "auto"` は `SystemInfo.graphicsUVStartsAtTop` に合わせて画像の上下を補正する。Mac Metalで確認済み。Windowsの描画APIごとの実測は未実施で、必要な場合は設定だけで `"on"` / `"off"` を指定できる。幅・高さは上限で、画面の縦横比を維持して偶数サイズに縮小する。送信中のみ `Application.runInBackground` を有効化し、停止時に元へ戻す。EditorのGameビュー非表示やbatchmodeでは `WaitForEndOfFrame` の制約があるため、実映像確認はGameビューまたは通常Playerで行う。`-nographics` では配信しない。

Player は次の優先順で設定を探す。

1. `-flyVideoConfig` の次の値（絶対パス）
2. 環境変数 `FLY_VIDEO_CONFIG`
3. Editor では `Runtime/Video/local/publisher.json`
4. Player では `Application.persistentDataPath/fly-video.json`

`-flyVideoConfig` が環境変数より優先される。設定が相対パス、存在しない、または `enabled` が false なら配信しない。Scene は変更しない。

Player起動例（実際のゲームと設定ファイルのパスへ置換）:

```sh
/path/to/Fly.app/Contents/MacOS/Fly -flyVideoConfig /path/to/Flylingual/Runtime/Video/local/publisher.json
```

```powershell
& 'C:\Games\Fly\Fly.exe' -flyVideoConfig 'C:\Dev\Flylingual\Runtime\Video\local\publisher.json'
```

secret は `FLY_VIDEO_PUBLISH_TOKEN` が最優先で、未設定なら publisher config の `tokenFile`（相対なら config と同じディレクトリ）から読む。backend も同じく `FLY_VIDEO_PUBLISH_TOKEN` を優先し、未設定なら backend config の `tokenFile` を読む。`init` が生成する token は 32 文字以上の ASCII で、local JSON と token は Git 管理外に置く。Windows から Mac backend へ publish する場合は、Mac 側と同じ token を安全な Git 外の方法でコピーするか、Windows 側で `FLY_VIDEO_PUBLISH_TOKEN` を設定する。

## browser 接続

ハエリンガルの設定で endpoint（例 `http://127.0.0.1:8880`）と stream を指定し、「映像をつなぐ」を押す。映像だけの確認なら `python -m http.server 4173 --bind 127.0.0.1 --directory Runtime/Player` でUIを配信して `http://127.0.0.1:4173/` を開く。会話も使う場合は既存Bridgeの同一origin `/player/` を使う。

browser は config、video-only recvonly offer、answer の順で接続し、その後 status を約500ms間隔で確認する。frame age が2秒を超える、publisherが切り替わる、または新しいvideo frameを描画できない場合はLIVEを解除し古い映像を非表示にする。再接続は明示操作で行う。ブラウザ側には送信用tokenを渡さない。

## Mac backend と Windows Unity を跨ぐ場合

推奨構成は Mac 上で backend と browser を同じマシンで動かし、Windows publisher から Mac の backend へ送る構成である。Windows 端末から Mac の backend を同じポートへ転送する例は次の通りである（値は置換する）。

```sh
ssh -N -o ExitOnForwardFailure=yes -L 8880:127.0.0.1:8880 <user>@<mac-host>
```

SSH は HTTP ingress の転送だけを担う。WebRTC の UDP を単純な SSH tunnel 転送として扱わない。backend と browser を別 PC に置く場合は、WebRTC candidate/NAT/TURN とネットワーク gate が別途必要である。現設定の `iceServers: []` は外部 STUN/TURN を使わない。

## 検証状態

`artifacts/video-protocol-validation.json` では synthetic publisher による 2 viewer、各 39 frame、640x360 decode、wrong origin 403、allowed origin 200、token 欠落 401、old sequence 409、競合 publisher 409、stale、cleanup 0 を確認済みである。`artifacts/video-compile.log` は Unity 6000.5.5f1 の batch compile が exit 0 である。

Mac Unity 6000.5.5f1のPlayer build成功（`artifacts/video-build.log`）。既存 `FlyLocomotionSandbox` の実ゲーム画面を60フレーム、960x540、約12fpsでWebRTC受信（`artifacts/video-unity-validation.json`）。このシーンのmotorは既存MOCKであり、実Brain連携の検証ではない。

初回の実画像で上下反転を発見し、送信側を補正して再buildした。修正版はハエリンガルUIで正しい向きのLIVE表示を目視確認（`artifacts/video/browser-unity-live.png`）。最終Unityコードではブラウザと同時に追加receiverで60frameを受信し、960x540・約10.9fps、Origin18771 HTTP200を確認（`artifacts/video-unity-final-validation.json`、source hashを含む）。Unity停止後にSTALE・旧映像非表示・明示再接続表示となることも確認。ブラウザのJS errorは0。会話・マイクは開始していない。

Windows実機、Mac/Windows跨機、Windowsの描画API別の向き、TURN、遅延・CPU使用率・長時間安定性は未検証。15fpsは設定値で、常時15fpsやE2E遅延を保証する値ではない。映像とBrainのsession対応、身体制御、音声はこの映像gateに含めない。

## 参照した一次資料

- [aiortc API](https://aiortc.readthedocs.io/en/latest/api.html): peer connectionとvideo track。
- [UnityのUV座標規約](https://docs.unity3d.com/ScriptReference/SystemInfo-graphicsUVStartsAtTop.html): 描画APIによる上下方向。
