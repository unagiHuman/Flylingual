# タイトルで接続完了を待つ（2026-09-15）

起動直後はタイトルに「接続中…」を表示し、開始ボタンを無効にする。Bridge制御接続、GPT Live（明示したテキスト版ではtext session）、選択言語の反映、実Brainの新鮮な受信、身体用TCPの接続・identity検証まで完了すると開始できる。実験的Brainのraw ready値をtrueに書き換えることはしない。

タイトルと初回操作説明を表示している間は、接続の準備だけ進める。PhysXの時間、motor source、マイク送信、プレイヤー指示、ゲーム側の環境・台本通知は開始まで抑止する。言語を切り替えると新しい言語で音声接続を準備し直し、その間は開始できない。接続が失われた場合も開始を許可しない。

開始ボタンの見た目だけでなく、`StartGame()` 自体も最新の接続状態を確認する。初回操作説明の最後の確認まで時間は停止する。接続エラーは日英の案内を表示し、制御接続が残っていれば再試行できる。ローカルサービス起動失敗ではアプリの再起動を案内する。

ハエたたきはタイトル・操作説明中、停滞時間と開始猶予の経過をともに0に保つ。開始後、実身体操作が有効になった時点から計測する。既存の「開始から60秒の猶予」「停滞20秒」「予告4秒」は維持する。接続待ちやポーズ中は計測を休止する。

専用の限定Player試験は `-flyConversationProbe -flyTitleConnectionProbe -flyConversationNoMicrophone` で実施する。`-flyTitleLanguageProbe` を追加すると、タイトルで言語を変更して再接続する経路も確認する。実Windows Brainを用い、未接続時の開始拒否、タイトル中の停止、カウント0、接続後の開始とカウント進行を記録する。通しコースと物理マイク試験の代わりにはしない。

## 実測

Unity 6000.5.9f1のJudge/CloudビルドはSucceeded（終了UTC 2026-09-14 16:17:06、BuildReportのエラーなし、既存の非推奨API等の警告44件）。そのPlayerを同梱した新しいZIPを展開し、実Windows Brain `127.0.0.1:18766` と実GPT Liveに接続した。

`artifacts/title-connection-20260915/player/probe.json` は `title_connection_gate_pass`。

- 未接続時の開始を拒否し、タイトルを開いたまま接続完了した。
- タイトル中の時間停止、身体位置の維持、停滞・開始猶予の両カウント0を確認した。
- タイトル上で英語から日本語へ切り替え、開始を拒否したまま新言語で再接続できた。終了時に元の表示言語へ戻した。
- 開始後4.031秒で、両カウントも4.031秒。予告・打撃なし。
- `MALECNS_EXPERIMENTAL`、受信raw ready=falseをそのまま記録、fresh=true、観測sequence 64→93、controller error空。
- 正常停止、終了コード0、Player例外0、強制cleanupなし、自己所有の残存processなし。物理マイクは明示的に無効化した限定試験。

Bridgeログ全体はBrainFrame 102件、sequence 4→105、Brain transport failure 0件。終了時の背景送信に既知の `ClientConnectionResetError` が1件残る。

probeの`status`文字列は接続成立フレームのUI更新前に取得したため「Connecting」のまま。UIの文言更新はソース確認であり、今回の結果でスクリーンショット確認済みとはしない。

成果物は `artifacts/submission-title-ready-20260915/Flylingual-Judge-Windows-submission-title-ready-20260915.zip`。SHA-256は `8aae4a307e49cb5dc04a94811ae14edfe2ecf3721407e49e36535a0baa870744`。全2,973ファイルのmanifest/ZIP照合に合格し、既存OpenAIキーの同梱検出は0件。

実行コマンド・選択ソースhash・設定/データを含むmanifest参照は `artifacts/title-connection-20260915/` に保存。既存作業ツリーのビルドで、別作業のUI・足音等も含まれる。通しコースと物理マイクは人手確認として残す。
