# Hybrid Intent Routing

Windows の操作意図判定は、確定済みの短い操作を deterministic fast rule で処理し、それ以外を loopback の local LLM に送る。local が raw `c=clarify` を返した場合だけ、発話に明示された方向・移動候補があり、発話が確定済みなら Responses へ一度だけ再解釈を依頼できる。これは不明な目的地や否定を別の操作へ変える仕組みではない。

## ルートと境界

処理順は次のとおりである。

1. `fast_intents` が確定した短い操作を返せば、その結果を既存の intent 検証へ渡す。
2. fast rule に該当しなければ、`llama_cpp` の label local 判定へ送る。
3. local の raw 結果が `{"c":"clarify"}` で、発話が確定済みかつ明示方向を含む場合だけ、残り時間内に Responses を1回呼ぶ。
4. Responses の構造化出力から採用するのは操作カテゴリだけとし、数量・時間・距離・継続・実行 ID は元発話と context から `ground_compact` で再構成する。
5. local、Responses のどちらも既存の9項目へ復元し、schema、`validate_intent`、現在の世代・取消・Brain admission を通す。

質問、local が正常判定した操作、local の通信失敗、JSON/schema違反、local grounding が拒否した結果では fallback しない。未知の目的地、否定、左右の競合、安全規則の変更要求も確認待ちのまま保持する。Responses の失敗・期限切れは新しい操作へ変換せず `clarify` として返す。Brain の ack は指示の適用確認であり、身体が動いた観測とは別である。

全体の intent deadline は共通の `intentTimeoutMs` で管理する。local 推論には最大1500msを割り当て、fallback はその処理時間を差し引いた残り時間で一度だけ実行する。期限切れ、世代変更、取消、接続断が起きた場合は結果を採用しない。

## 設定例

既定の `localIntentResponsesFallback` は `false` である。Hybrid を明示的に使う場合は、`Runtime/Config/hybrid-intent.example.json` を既存の local 設定へ必要なキーだけマージする。既存の `Runtime/Config/local.json` 全体を上書きしない。Responses は既存の `intentModel` と Bridge プロセスの `OPENAI_API_KEY` を使用する。

```json
{
  "conversation": {
    "intentProvider": "llama_cpp",
    "localIntentUrl": "http://127.0.0.1:11436",
    "localIntentModel": "qwen3.5:4b",
    "localIntentFormat": "label",
    "localIntentCachePrompt": true,
    "localIntentResponsesFallback": true,
    "intentTimeoutMs": 8000
  }
}
```

label の local 出力は操作カテゴリだけで、時間・距離・継続の値をモデルに生成させない。local の fast rule と `ground_compact` は、通常の local intent と fallback 後の Responses intent で共通に使う。

## 起動と確認

llama.cpp native server を先に用意し、Bridge の provider と URL を例に合わせる。Ollama と native server を同じ GPU へ同時に載せない。判定結果の diagnostics では `deterministic`、`label_llm`、`responses_reinterpretation` を分け、`fallbackAttempted` と `fallbackOutcome` で試行・結果を確認する。

評価はテキスト fixture で行い、fast rule、local label、明示方向付き clarify、fallback 不許可条件、期限切れを分けて確認する。local の成功を Responses の成功へ読み替えず、fallback が実行された場合も最終 intent の validation と admission を通過したかを別に記録する。

## 未検証範囲

実機の Unity、実 Brain、実 API、実音声を含む E2E は未検証である。local intent のレイテンシや fixture の一致率だけで、ゲーム全体の完成、身体動作、体感遅延を判定しない。既存の Transcript 経路を使用し、server 側には会話・文脈世代の再確認と、古い判定エラーの副作用破棄を追加した。関連するオフライン単体テスト145件が成功した。
