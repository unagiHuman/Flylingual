# 音声会話対応の提出版（2026-09-15）

提出ZIPの既定をGPT Live音声版へ変更した。審査員のキー入力は不要。OpenAIキーは、ユーザーの明示許可を受けて本人のVercel `hayeringual-api` 本番環境へ登録した。配布するのは音声セッション発行に用途を限定したアクセス資格であり、OpenAIキーではない。

新規セッションの発行期限は `2026-09-18T15:00:00Z`（日本時間9月18日いっぱい）。サーバー側の予算やキー自体の有効期限を保証するものではない。既存セッションを期限時刻に強制終了する処理はない。

## 変更

- Vercelの `/api/fly/voice/session` で資格・期限・入力形式を検査し、GPT LiveのWebRTC接続を発行する。モデルは `gpt-live-1` を維持。
- Bridgeにaiortc/PyAVの音声入出力を追加。既存のマイク・字幕・音声再生・神経フィードバック経路を利用する。
- コーデックの初回importを別スレッドへ移し、ロード中のBrain受信とSTOP通信を妨げない。PCM送信時刻は絶対時刻で管理する。
- Judge/Cloudの起動時に音声設定がテキスト設定で上書きされないよう修正。portable Pythonへ音声依存を同梱する。
- `Package-Submission.bat` は音声資格が欠けていると失敗する。意図したテキスト版だけ `--text-only` を使う。
- 開始前・停止中の地形通知を抑止し、「会話のみ」で不要な操作権エラーを出さないようにする。

## 検証範囲

Python関連83テスト、Backend20テスト・typecheck・Next.js buildを実施し、合格。Unity 6000.5.9f1のJudge/CloudビルドもSucceeded。BuildReportに残ったエラー1件はCLI要求の5秒待機超過で、C#コンパイルエラーではない。警告44件は既存APIの非推奨等とPlayer用Pipeline設定なしの通知。

実Vercel/GPT Liveへ24 kHz mono PCMの録音済み発話を送る限定試験では、入力文字起こし2デルタ、返信文字起こし14デルタ、返信音声741,088 bytesを受信した。これは物理マイクの試験ではなく、Brain/Unityを含まない音声通信の試験である。

最初のPlayer試験で初回DLLロードによるBrain送信タイムアウトを発見し修正した。途中のv3試験は停止と新しい操作開始が競合しincomplete、同一ZIPの再試験は音声開始・再生・停止・終了に成功したが、地形通知の操作権エラーでincompleteだった。これらの不合格原本は保持し、成功扱いに変更しない。

実行コマンド・結果・録音・選択ソースhashはローカルの `artifacts/voice-submission-20260915/` に保存する。各ZIPのmanifestは同梱ソース・設定・データのSHA-256を含む。ビルドは既存作業ツリーを使用しており、別作業のUI・足音等も含まれる。単一のclean commitから再現した成果物とは扱わない。

通しプレイ、物理マイク、別PCでの受入れはユーザーが後で行う。実測のBrain ready値を接続成功だけでtrueへ読み替えない。

## 最終成果物とPlayer確認

`artifacts/submission-voice-20260915-release/Flylingual-Judge-Windows-submission-voice-20260915-release.zip`

SHA-256: `32565f40056e121f1d20c5ef2f9e04b5711e42a45f82df4135bdd6b5042c35e8`

manifest 2,973ファイルとZIP内容の全ハッシュ照合に合格。manifestを含む2,974ファイルの既存OpenAIキー完全一致スキャンは検出0件。

このZIPを別フォルダへ展開し、同梱Player/Python/実Windows Brain（`127.0.0.1:18766`、`MALECNS_EXPERIMENTAL`）で限定実行した。`player-release/runner.json` は `reply_audio_pass_no_microphone`。自動開始=true、live=true、停止=true、音声72,928 bytes、非ゼロ再生53,084 samples、字幕3デルタ、sequence=94、error空。会話のみの試験なのでoutputInhibited=true、受信brainReady=falseをそのまま記録した。物理マイク送信は0。終了コード0、例外0、強制掃除なし、自己所有の残存processなし。

実行方法は `artifacts/voice-submission-20260915/verify_player_release.py` に保存した。既存コースを進める試験や、音声命令による移動の全経路を今回の結果で合格とはしない。

BridgeログはBrainFrame 112件、sequence 4→115、Brain transport failure 0件。Player終了のcontrol client切断後に背景送信の `ClientConnectionResetError` が1件記録された。通常終了時の残るログ通知として記録し、接続中のBrain障害とは混同しない。

手順・期限・発行制限の詳細は [提出版ZIPの作成](Package-Submission.md) を参照。
