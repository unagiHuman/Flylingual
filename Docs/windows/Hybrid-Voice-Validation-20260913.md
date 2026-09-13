# Hybrid 音声・実Brain検証（2026-09-13）

実際の `Runtime/Config/local.json` の conversation に hybrid-intent.example.json の項目をマージして有効化した。既存の他設定は保持。Playerが読む windows-stack.local.json の bridgeLocalConfig と一致し、windows-native.local.json は存在しない。llama_cpp / label / cache / Responses再解釈有効、全体期限8000ms。Responsesモデルは既存設定の gpt-5.6-luna。ローカルサーバーは tools/local_llama.ps1 Prepare で準備済み。再起動後も同サーバーの準備が必要。

## 合成音声から身体まで

Unity Player、実GPT-Live、Windows実Brain（127.0.0.1:18766）、既存BrainFrame・motor・PhysXを使用。backendは MALECNS_EXPERIMENTAL、ready受信値はfalseのまま。readyを昇格させていない。

`tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v2/manifest.json --suite duration --capture-test-transcript --seconds 180 --output artifacts/hybrid-voice-validation-20260913-duration` はpass。

| 操作 | 音声終了→身体開始 | 適用後fresh frame進行 | 判定route |
|---|---:|---:|---|
| 前進 | 993.8ms | 30 | rules |
| 右旋回 | 1404.9ms | 27 | rules |
| 左旋回 | 1504.5ms | 23 | model |

3件すべてBrain適用・身体開始を検出。停止済み、Player例外0、終了code0、残留所有PIDなし、Brain/Bridgeポート解放を確認。runner-metadata.jsonにsource/config/data/artifact hashと依存版を保存。単発3件であり統計的なp95や長時間安定性を主張しない。model表記は詳細provider分岐の識別を保証しない。

先行smokeは前進1084.9ms、右旋回1712.1msで身体開始、STOP適用を観測したが、multiple_delegations_for_fixtureによりincomplete。原本 artifacts/hybrid-voice-validation-20260913-1 を保持し、成功に置き換えない。

## 実マイク

通常Player（PID22168、起動ログ artifacts/hybrid-microphone-player.log）をマイク有効で起動。ユーザーが実際に発話し「動いて止まった」と回答。Bridgeのvoice_pipelineで入力音声・Transcript・非ゼロ返答音声を確認し、execution_started / command_appliedで前進・旋回の実Brain適用を確認した。実マイク試験の身体動作と停止はユーザー目視の確認であり、合成音声試験の計測値を流用しない。ユーザー音声本文の追加保存は有効にしていない。

## Responsesと残課題

実Responsesへ「右側に寄って進んで」を直接1件送信し、right_then_forwardを3181.9msで受信。記録は artifacts/hybrid-real-api-20260913-responses-direct.json。これは実API接続の証拠であり、Local clarify→Responsesの自動振り分け経路の成功ではない。

自然文のlocal追加試験では誤分類を観測。「右側に寄って進んで」はleft_then_forwardがgroundingで拒否され確認待ち。「もうちょっと右行って」はnudgeでなくTURN_R。「前へ様子を見ながら」は条件付きplanでなくFORWARD。現仕様では正常形式の誤分類やgrounding拒否をResponsesへ送らないため、残課題として保持する。原本は artifacts/hybrid-real-api-20260913-valid.json と hybrid-real-api-20260913-fallback.json。最初の hybrid-real-api-20260913.json はPowerShell出力の文字コードを確認できないため受入れ証拠に使用しない。

基本音声操作と実マイクでの動作・停止は確認済み。自由な自然文の精度、重複delegation、自動再解釈の実API往復、長時間試験、ローカルサーバーのゲーム起動終了との完全な連動は未完了。コミット・プッシュはしていない。
