# ハエリンガル — Voice & Vision

Windows／Macで同じHTML/CSS/JavaScriptを使う、声中心のプレイヤー画面です。画面を **WebRTC実映像・ハエリンガルアイコン・音声操作** に絞りました。文字入力・会話履歴・手動方向ボタンはありません。APIキーや発話本文を保存しません。

## 起動

実音声には、Bridgeの `/player/` を開きます。標準は `http://127.0.0.1:8771/player/`。別ポートでも同じソースが動作し、その画面と同じoriginの `/ws` を使います。接続設定は右上の歯車にあります。

画面だけのプレビューはリポジトリルートから起動します。

```sh
# Mac
python3 -m http.server 4173 --bind 127.0.0.1 --directory Runtime/Player
```

```powershell
# Windows
py -m http.server 4173 --bind 127.0.0.1 --directory Runtime/Player
```

`http://127.0.0.1:4173/` では見た目と、許可originを設定した映像バックエンドへの接続を試せます。BridgeのOrigin制限を維持するため、4173やfile://から声の接続はしません。未接続のアイコンはSAMPLE、実接続後に新しい観測がない場合は「わからない」と表示します。

単一HTMLが必要な場合は `node Runtime/Player/build.mjs` を実行します。依存パッケージなしで、画像・CSS・全JSを含む `dist/player.html` を生成します。配信時はこのファイルを同じBridge originから開けます。`dist` はGit除外です。

## 声の操作

最初に「話しかける」を押し、音声送信と料金の案内から「音声で開始する」を選びます。マイク権限を許可すると、以後は声で指示できます。準備中の同じボタンは中止、会話中は終了です。緊急停止も常に見える位置にあります。

一つの開始操作の内部で、次を順番に確認します。

1. 同一originのBridgeに接続し、最初の `bridge_state` を受信。
2. 必要な場合だけ設定profileへ `switch_target`。切替完了・新接続を確認。
3. 古い会話があれば停止完了を待つ。
4. `set_owner: gpt` の新epochと出力抑止を確認。
5. 現epochで送信したSTOPの `requestId` とBrain適用を照合し、750ms以内の停止状態（forward/turnとも絶対値0.02以下）を確認。受付ackやmotorゼロだけで先へ進まない。
6. `conversation_start` → `live` と `voiceControlAvailable=true` を確認し、停止状態の鮮度も再確認。
7. 明示した開始操作に基づく `resume` を送り、現在の抑止解除を確認。
8. マイクを開始。PCM16 little-endian / mono / 24kHz / 100msごとの音声に `controlEpoch` を添えて送信。

開始中止・終了・緊急停止はローカル抑止、音声キュー破棄、マイク終了、Bridgeへの停止／会話終了要求を行います。接続断、古い観測、epoch変更、`voiceControlAvailable=false` で自動再開しません。「もう一度話す」が次の明示開始です。キャンセル済みの非同期マイク許可は世代で破棄します。BrowserはActionやmotorを生成せず、声の意図翻訳はバックエンドに任せます。

返答再生とマイク送信の許可条件は分離しています。返答は明示開始で有効化したAudioContextを使い、接続準備中も保持します。再生キューは最大5秒、再生中とその後200msはマイク送信を抑えます。旧epoch・切替・終了・切断ではキューを破棄します。マイク非対応や権限拒否の場合は停止して理由を表示します。

## 話し方・声・言語

歯車の「話し方・声・言語」で「設定を読み込む」を押すと、会話を開始せずにBridgeへ接続し、現在の設定と選択肢を取得します。対応する声は `conversation_options` の値から表示します。旧Bridgeや不正な設定を受信した場合は適用できません。設定の読み込み自体はマイク・会話API・Brain操作を開始しません。

言語は日本語／英語、話し方はfriendly／curious／calm／customを選択できます。カスタムの説明は最大800文字（Unicodeコードポイント数）で、人格設定は発話表現のみを変えます。安全機能や6 Actionの操作権限は変更しません。音声ファイルのアップロードや声の複製は含みません。

「会話を終了して設定を適用」はローカル音声停止→Bridgeの会話停止完了と出力抑止を確認→`configure_conversation`を送る順です。要求には一意の`requestId`、現在の`controlEpoch`、編集開始時の`expectedRevision`を付け、対応する応答・設定内容・更新後revisionを照合します。古いrevision、接続断、タイムアウトでは自動再送しません。成功しても会話／マイク／操作を再開せず、次の明示的な「話しかける」で反映します。

heartbeatで編集中の内容を上書きしません。別操作によるrevision更新は競合表示とし、「設定を読み込む」で明示的に最新値を確認します。ブラウザには人格文・設定を永続保存せず、Bridgeの現在値を正とします。設定画面の「閉じる」は会話設定を適用しません。

言語切替の範囲は会話の応答／命令翻訳、新しい設定欄のラベル・案内、主画面の発話例です。主画面の固定文言、既存接続設定、動画サービスのエラー等は日本語のままで、全画面の国際化は未対応です。

## WebRTC映像

`video.js` は別担当が実装した独立受信機です。Brain・音声・アイコンに映像からの制御を混ぜません。既定接続先は `http://127.0.0.1:8880`。最初の「映像をつなぐ」は設定内の同じフォームを送信します。映像と声はそれぞれ独立して開始・終了できます。

| 接続 | 契約 |
| --- | --- |
| GET `/api/video/config` | `iceServers`, `streams`, `staleAfterMs` |
| GET `/api/video/streams/{id}` | `state`, `sequence`, `frameAgeMs`, `publisherId`, `source`, `width`, `height`, `viewers` |
| POST `/api/video/streams/{id}/offer` | recvonly videoの `{type: "offer", sdp}` → `{type: "answer", sdp, sessionId}` |
| DELETE `/api/video/sessions/{sessionId}` | 閲覧セッションの終了 |

公開APIは `window.FlyVideo.state()` と `disconnect()`。状態変更は `flyvideochange` で受け取ります。UIの描画は、新しい動画frameと配信元liveの両方を確認した場合だけLIVEとします。2秒超の古い映像、publisher変更、切断時は映像を隠します。rVFCの観測を維持するため、非表示は受信機のinline opacityを使い、CSSでdisplay:noneへ上書きしません。遅延answer、再接続、pagehideでは旧セッションを解放します。

映像サービス側は、この画面の正確なoriginを `allowedOrigins` へ設定してください。通常の8771／4173と、検証用の別ポートは別originです。ブラウザへpublisher tokenを持たせません。異なるマシンではサーバー側で既存のSSHトンネル等を設定し、ブラウザはloopbackへ接続します。映像とBrainが同じ身体sessionであることは、現行契約では未検証です。

## ハエリンガルアイコン

`assets/moods.png` は4表情の透過スプライト（2×2）です。built-in image_genで作成し、実プロンプトを `assets/moods-prompt.txt` に残しています。CSSで興味・探索・休息・傾聴を切り替えます。実映像とは別の表示です。

- 新しいBrainFrameの旋回出力 →「あっちが気になる」。
- 新しいBrainFrameの前進出力 →「ちょっと、たんけん」。
- 運動出力ゼロ付近 →「ひとやすみ」。同時にマイク受付中なら「きいてるよ」。
- stale／未接続 → 不明表示。最後の表情を現在の気持ちとして固定しない。
- 現在のepochの会話サービス字幕は最新一節だけ表示し、20秒で観測ベースの文へ戻す。字幕の履歴・保存はしない。

これらは観測から作るキャラクター表現です。要求Action、受付ack、映像接続成功だけで気持ちや動作を断定しません。本当の感情を測定したとは表示しません。Brain readyと映像LIVEは分離し、設定の詳細から確認できます。

## 責務と検証

`index.html` / `styles.css` は3機能の画面、`app.js` は音声開始と設定適用フロー・アイコン表示、`core.js` はframe/session/epoch検証、`settings.js` は会話設定フォーム、`audio.js` は音声入出力、`video.js` はWebRTC受信、`build.mjs` は単一HTMLの生成を担当します。Bridge／Videoサーバー・Unity・契約の正本は別担当です。

[Bridge契約](../../Contracts/bridge-v1/protocol.md)、[共通設計](../../Docs/Brain-GPTLive-CrossPlatform-Design.md)、[実APIの別担当検証記録](../../Docs/integration/Live-Browser-Validation-2026-09-12.md)を参照してください。

今回のUIはJS構文、HTMLの60個のIDと参照、WebRTC受信機の必須ID、約1MBの単一HTML生成、文字入力／手動Action送信の撤去を検査済みです。4173と18771の `/player/` 配信はそれぞれHTTP200を確認しています。

WebRTC担当の実測は `artifacts/video-unity-validation.json`（実Unity、960×540、60フレーム、約12fps）を読み取り確認しました。上下補正後の実ブラウザ画像 `artifacts/video/browser-unity-live.png` と `browser-live-observation.json` も確認済みです。後者は `videoLive=true`、`micActive=false`、`moodSource=SAMPLE`、`brainReady=false`、`bodyBrainSessionMatched=false` を分離して記録しています。映像源は検証用UnityのMockMotorSourceで、実Brainと連動した身体ではありません。新UIでのLIVE表示→配信停止後STALE・古い映像非表示・JS error 0も担当から報告されています。実測の正本と最終結果は [映像配信の手順と検証](../../Docs/integration/Unity-WebRTC-Video.md) を参照してください。

2026-09-12、18771の実ブラウザでマイク開始前に `fresh_stopped_brain_required` が発生する問題を修正しました。STOP適用前のmotorゼロ観測でresumeしていたため、現epochのSTOP適用を待つように変更しています。既存Bridgeのままepoch41/request36のSTOP適用→resumeと、画面の `voicePhase=listening` / `micActive=true` を確認。終了ボタン後は `voicePhase=stopped` / `micActive=false`、ブラウザerror/warnは0でした。マイク拒否・未接続・利用不可の具体的なエラーも開始フローに返し、汎用エラーで上書きしません。

会話設定UIも18771の新Bridgeで実測しました。初回取得・同一WebSocketで再読込、en/quartz/customの保存（revision1）、ja/marin/friendly/空への復帰（revision2）に成功。両適用後ともconversation off、micActive=false、outputInhibited=true、ready=falseを確認しています。絵文字800個の入力と801個の適用拒否（revision不変）、編集中の値の維持、ブラウザerror/warn0も確認し、最後に制御WebSocketを解放しました。画面・観測値は `artifacts/player-settings/` に記録しています。

この検証では、圧縮を交渉した接続の初回送信でWebSocket 1002が再現し、別担当がBridgeのloopback制御WebSocketを非圧縮に変更しました。修正後の設定保存往復は成功しています。古いrevisionを外部から注入する競合試験はUIでは未実施で、Backendの検証範囲です。会話設定の保存確認中に実API・マイク・映像・手動Actionは開始していません。

新UIの実発話→Brain指示→返答音声の通し操作、各Windows/Macブラウザ、echo抑止の実機検証は未実施です。マイクON確認を発話認識や身体動作の成功とは扱いません。任意のWebMCP読み取りツール `fly_read_observation` は、非対応ブラウザでは登録を省略し、制御／接続を提供しません。
