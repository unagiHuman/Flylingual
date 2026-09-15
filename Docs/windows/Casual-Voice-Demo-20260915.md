# 雑談を挟む合成音声デモ

`tools/verify_native_voice.py --suite english-chat-demo` と `artifacts/test-voice/en/chat-test-manifest.json` を使用する。既存前進・停止音声に、気分・空腹・ハエの暮らしを尋ねる3つの英語音声を追加した。Windows Ziraによるローカル生成、24kHz/mono/PCM16。生成スクリプトは `artifacts/test-voice/generate-chat-en.ps1`。

シナリオは前進→気分→空腹→停止→ハエの暮らし→再開→停止。実PCM入力を使用し、テキスト入力への置換や返信音声の事前生成は行わない。質問は認識候補との時間的対応、操作を伴わない分類、返答音声の開始と0.3秒静音を確認する。音声終了後に分類最大12秒・返信終了最大18秒を待つ。回答内容の正しさやprovider response IDとの対応までは自動合格条件にしない。

`--recording-gate <新規ファイル>` で起動すると、接続後に出力ディレクトリへ `recording-ready.txt` を作成し、開始ファイルを最大300秒待つ。開始後は最短60秒表示する。Game Barの録画開始後にファイルを作成する。`--monitor-fixtures` は入力と同じPCMをアプリ内AudioSourceで再生し、Game Barのゲーム音として収録できるようにする。

雑談の明確な完全表現を `fast_intents.py` の非操作質問へ追加した。疑問文を移動指示へ変換せず、部分一致で方向を補わない。通常の安全停止は質問が生成した操作とは扱わない。返信終了の確認タイムアウトや、既に自動停止した後の音声停止は未完了として残し、表示用デモを続行可能にした。

check01–03の失敗も `artifacts/voice-tests/` に保存。check04では3質問すべてで非操作分類と返答再生開始・終了を確認。これは実Windows Brainとstandalone Playerでの確認であり、Editor Play Modeは使用していない。録画の結果は録画ディレクトリへ別途記録する。
