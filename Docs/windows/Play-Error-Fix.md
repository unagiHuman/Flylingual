# プレイ時のエラー表示確認・修正（2026-09-14）

Consoleに残っていたSwatterのNullReferenceExceptionは9月13日23:30 JSTの旧UI実装、Pipelineのタイムアウトは同23:33のビルド操作の記録。最新コードで起動→予告→GameOverを再確認し、新規Console例外はなかった。

一方、画面右上の`old_epoch`が残る現象は再現した。接続・停止の世代切り替え前に送信した地形観測をBridgeが正しく拒否した際、UIがその通知を現在の障害として保持し続けていた。

Bridgeのold_epoch応答に限定して要求種別と送信／現在epoch、明示マーカーを追加。Unityは明示された旧epochの`local_safety_observation`と`blind_run_cue`だけを診断ログへ分類する。操作・開始・再開・設定変更のエラー、情報不足のエラーは従来どおり表示する。エラーの一律無視・正常Frame到着による一律消去はしない。

変更: `Runtime/Bridge/server.py`、`ConversationSessionController.cs`、`tools/test_stale_observation_errors.py`。

検証: Python13件合格。Unityコンパイルエラーなし。Windows実Brain127.0.0.1:18766／MALECNS_EXPERIMENTAL／raw ready=falseで起動からGameOverまで確認。epoch1→3、5→6の地形観測拒否は診断ログになり、Error=nullを維持。TCP sequence205、20.0105秒で通常のSwatter GameOver。新規Console errorなし。証拠は`artifacts/play-error-fix-20260914/console.json`。

実プレイ検証はEditor。ユーザーが見たエラーが別のものだった場合、そのエラーまで解消したとは断定しない。
