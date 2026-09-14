# 提出版ZIPの作成

既定は **GPT Live音声会話版**。マイク・スピーカー（推奨ヘッドセット）とインターネット接続が必要。審査員によるOpenAIキー入力は不要で、キーはVercel側にのみ置く。提出用アクセスは日本時間2026-09-18いっぱいまで有効（新規セッション発行期限）。

1. Unityの `Flylingual > Build Channels > Configure Windows Build` で、Channelを `Judge`、LLM providerを `Cloud` にして、公開済みのApplication backend URLを入力し、Windows Playerをビルドする。
2. リポジトリ直下の `Package-Submission.bat` をダブルクリックする。
3. `SUCCESS` と表示されたZIPを提出する。出力先は `artifacts/submission-年月日-時分秒/`。画面と `archive-receipt.json` にSHA-256も記録する。

batはUnityのビルドを行わない。既存の `artifacts/hayeringual-builds/Judge-Cloud` のPlayerと現在のBridge/Brainソースを組み合わせるため、変更後は必ず先にUnityを再ビルドする。Playerの開発ログやDoNotShipフォルダはコピーしない。元ビルドや過去ZIPは上書きしない。

初回のみ、portable Pythonがなければ、リポジトリ直下で次を実行する（uvが必要、Pythonと依存ライブラリをダウンロードする）。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/prepare_judge_python.ps1
```

出力元を変える場合：

```bat
Package-Submission.bat --player "D:\Builds\Judge-Cloud" --output "D:\Submissions\Flylingual-new"
```

実行用Pythonは `.venv-bridge/Scripts/python.exe`、なければPATHの `python` を使用する。配布用Pythonは別途 `--python-root` で指定可能。既存の `package_judge.py` で必要ファイルを同梱し、manifestとZIP内の全収録ファイルのSHA-256を照合する。失敗中のZIPは `.partial` のまま残し、診断用フォルダを自動削除しない。

この処理はパッケージ作成・整合確認のみ。ゲーム起動、実Brain検証、通し試験、別PCでの受入れは実行しない。

## 音声版の準備と設定

作成者の `artifacts/voice-access/review-pass.txt` に、Backendへ登録した提出用の限定アクセス資格を用意する。これはOpenAI APIキーではない。batはこのファイルを同梱するため、ZIPの公開再配布は避ける。作成者の別PCでは `--voice-access <ファイル>` で指定する。資格がなければ失敗し、無断でテキスト版へ切り替えない。テキスト版が必要な場合だけ `--text-only` を指定する。

既存portable Pythonへ音声依存を追加する場合：

```powershell
uv pip install --python artifacts/judge-python/portable/python.exe --target artifacts/judge-python/portable/Lib/site-packages aiortc==1.14.0
```

Backend本番には `OPENAI_API_KEY`、`HAYERINGUAL_VOICE_ACCESS_PASS`、`HAYERINGUAL_VOICE_ENABLED=true`、`HAYERINGUAL_VOICE_EXPIRES_AT=2026-09-18T15:00:00Z` を設定する。キー・アクセス資格の値をGit、コマンド引数、ログへ残さない。環境変数変更後は再デプロイする。`/api/fly/voice/session` がGPT LiveのWebRTC SDP交換を認証し、音声は同梱PythonとOpenAI間で送受信される。既存の開発用WebSocket接続も保持する。

認証routeにはインスタンス内の発行制限（IPごと3回/分、全体30回/分）がある。Vercel WAFの追加は現行プランで拒否されたため、分散制限・日次支出上限・既存セッションの強制期限切れは保証しない。期限は新規発行時に検査する。緊急時はBackendを無効化し、必要に応じてOpenAI側の期間限定キーを停止する。
