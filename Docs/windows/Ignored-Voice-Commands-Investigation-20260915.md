# 音声命令が無視・置換される現象の調査

2026-09-15。原因調査後、ユーザー承認で以下の修正と再検証を実施。

## 修正後の結果

`fast_intents.py`で限定した挨拶接頭辞（Okay/OK/Alright/All right）直後の句読点を吸収し、残りの完全命令文を検証する。否定・条件・複合指示から方向語だけを拾わない。`server.py`では音声・直接入力のclarifyを経路ヒントの操作へ昇格する2箇所を削除した。既に受理された移動の補助とBrain・物理は維持する。

関連60テスト成功。実Windows Brainで`ignored-command-fixed-20260915-check01`を実施し、再開は期待FORWARDでpass、雑談3件もpass。移動・停止4件はすべて期待する操作が適用された。最後のSTOPのみ自動期限停止の後だったためvoice_stop_causality_not_confirmedでrunner全体はincompleteのまま。所有プロセス正常終了・ポート解放確認。

`artifacts/submission-voice-command-fix-20260915/`に修正版ZIPを作成。Unity Playerは既存提出版を再利用し、Python2ファイル・README・manifestのみ更新。全manifest SHA256検証済み。今回変更しない音声認識サービスの無応答や、未実証のrevision取消まで直ったとは扱わない。

## 現行版で再現した原因

standalone Playerと実Windows Brain（127.0.0.1:18766、MALECNS_EXPERIMENTAL）で、既存の合成音声を使用した。`ignored-command-investigation-20260915-check02` の `05_resume` が期待FORWARDに対しTURN_Lとなった。

- 音声: `Okay, keep moving forward again.`
- 認識: ` Okay. Keep moving forward again`。方向語forwardは残っている。
- Player時刻66.590秒: 音声開始。
- 71.115秒: 31文字をfinalized=trueの候補として処理。
- 71.342秒: モデル分類clarify。その直後、コース補助がTURN_Lの操作へ置換。
- 71.546秒: Brainへの適用確認。

`Runtime/Bridge/fast_intents.py` は `okay, keep moving forward again` とカンマなしの形に完全一致するが、`okay. keep moving forward again` は一致しない。音声認識が挿入した句読点で処理経路が変わる。直接関数確認でも、カンマ版はFORWARD、ピリオド版はNone（モデルへ委譲）となった。`Okay. Turn right.` / `Okay. Turn left.` もモデル経路へ進むが、これらの実音声失敗までは今回再現していない。

`Runtime/Bridge/server.py` の `transcript_utterance` はfinalizedなclarifyを `goal_route_proposal` へ渡す。`Runtime/Bridge/goal_route.py` は元の方向語を検査せず、最新コースヒントを新規操作にする。そのため明確な前進要求でもモデルがclarifyとした時点で別方向へ置換される。身体の回転量とは別の、認識後の制御経路の問題である。

## 過去の実測との照合

- `chat-demo-20260915-check04`: 同じ再開音声からforwardが脱落し、`Okay. Keep moving again` → clarify → TURN_R。認識欠落と上記置換処理の組合せ。
- `gamebar-demo-20260915` case4: STOP音声3.2895秒、33チャンクを送信。Bridge側音声区間97500–100800msも記録。認識文字列0文字、候補・適用なしでタイムアウト。接続・epoch・session・freshnessは維持。この例では認識結果が返らない段階で止まっている。サービス側が認識を返さなかった理由は未確定。
- 最新録画 `gamebar-movement-chat-20260915-retry02` は全移動指示が適用されており、これだけでは断続的な取りこぼしを否定できない。

## 再現条件と結果

```text
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/test-voice/en/chat-test-manifest.json --suite english-chat-demo --capture-test-transcript --monitor-fixtures --exe artifacts/english-demo-build/FlylingualConversation.exe --output artifacts/voice-tests/ignored-command-investigation-20260915-check02
```

初回check01は既存提出版によるポート使用で起動前に停止。ユーザー承認で提出版を正常終了後、check02を実行。7ケース中、再開指示がunexpected_action。他6ケースはpass。runner全体はincomplete。Player正常終了、所有プロセス残留なし、ポート解放済み。raw brainReady=falseはそのまま扱う。実行ファイル・ソース・設定・データhashと依存版は同ディレクトリのrunner-metadata.jsonに保存。物理マイクでの同一現象の再現は今回未実施。

## 未実証の別候補

消費済み音声候補の実行待ち中に別の認識断片が来ると、transcriptRevision不一致でstale_transcriptとなり得る。コード上の疑いであり、今回の実測原因とは区別する。

## 修正の方向

句読点だけの違いを安全な完全命令文の範囲で吸収し、明示された方向をコースヒントで上書きしない。解釈できない場合は確認を返す。音声の認識未着・解釈拒否・適用失敗も別々に可視化する。確認・修正なしに任意の文から方向語だけを拾う変更は、否定文や条件文を誤操作にするため避ける。
