# 音声認識後の指示変換修正（2026-09-15）

通常の Windows native launcher は `llama_cpp` 設定時、インストール済みの固定 llama-server と qwen3.5:4b モデルを起動し、health と warmup が完了してから Bridge を開始する。以前はこのサービスが起動せず、認識成功後に `intent_translation_failed` となっていた。新規ダウンロードや外部サービスは追加していない。

対象は既存の localhost:11436 構成のみ。別プロセスが使用中の場合は、そのプロセスを利用・停止せず起動エラーにする。Player 終了時には自身が起動したプロセスのみ終了する。起動ログはその run の `local-intent.log`。Cloud 等の他 provider はローカル LLM 起動を行わない。

完全な英語の前進・停止・再開・微調整の言い回しを既存の限定文法に追加した。条件文・否定・複合指示を単語一致で操作に変えず、通常の意味解釈経路へ渡す。接続失敗とタイムアウトは、それぞれ `intent_service_unavailable` と `intent_translation_timeout` に区別する。

検証対象は `artifacts/english-demo-build/FlylingualConversation.exe` の standalone Player。Editor の Play Mode は使用していない。音声は既存の `artifacts/test-voice/en/` の PCM WAV をそのまま認識経路へ投入する。Brain は実 Windows LiveTcp、`MALECNS_EXPERIMENTAL`。物理マイクの集音確認・コースクリア・録画は、この変換確認と区別する。

途中の `english-demo-20260915-fixed02` では、一文の短い間で発話が確定して末尾の stop が別操作になる不具合が判明した。検証器の重複判定は緩めず、通常入力にも適用する発話確定処理を修正した。音響静穏700msと最終認識テキストの安定700msの両方を確定条件にする。従来のノイズ時の意味解釈経路は維持している。この変更は反応時間とのトレードオフがあり、任意の長い文内休止を完全に解決するものではない。

## 最終確認

`artifacts/voice-tests/english-demo-20260915-fixed03/` に report・events・observations・runner-metadata を保存。試行数1、02_continue→07_stop→05_resume→07_stopの4入力すべてで期待するFORWARD/STOPが実Brainへ適用された。前進・再開の身体移動、両STOP後の静止を観測し、この試行では余分な発話分割による操作はない。音声ファイル終了から適用までは順に約1100/1098/841/920ms。

最後のSTOPは、再開の4000ms期限による自動STOP適用（31.57秒）の後（31.89秒）だった。従って音声停止の因果性gateは未確認で、全体は `incomplete / voice_stop_causality_not_confirmed` のまま保持する。最初のSTOPでは期限切れ前の音声停止が確認できている。試験を通すために再開指示を無期限へ変更していない。

関連回帰134件が通過。その後、遅延断片テストを実時間600msの到着遅れへ強化し、該当33件を再実行して通過。Player例外0、所有プロセス残留なし、11436/18766/18770/18771解放確認。所要35.063秒、process tree peak RSS 2427359232 bytes。ソース・設定・データのhashと依存版は runner-metadata に記録（設定内容や秘密情報は転載しない）。raw brainReady=falseをreadyへ昇格しない。

物理マイク・残り6音声・コースクリア・Game Bar録画は未検証。録画対象は引き続きstandalone Player。
