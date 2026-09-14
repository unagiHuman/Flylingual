# 提出版ZIPの作成

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
