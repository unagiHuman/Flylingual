# ローカル LLM 短ラベル・prefix cache 評価

操作意図のローカル判定で、短いラベル出力と system prompt の prefix cache が遅延へ与える影響を比較した記録である。評価はテキスト入力だけを対象にし、Unity、Brain、実音声、ゲーム全体の操作感は含めない。

## 評価条件

`artifacts/local-llm/label-cache-cases.json` の40発言を同じ順序で各1回評価した。既知ケースの回帰であり、独立した最終 holdout ではない。Ollama baseline と llama.cpp native の比較は同じ qwen3.5:4b GGUF（sha256 `81fb60c7daa80fc1123380b98970b320ae233409f0f71a72ed7b9b0d62f40490`）を使い、同じ1 slot・compact intent 経路・1500ms timeoutで測定した。

native ではモデルの chat template を `/apply-template` で確認し、cache 有効時は固定 system prefix を checkpoint に入れて `n_predict=0` の prefill を行った。その後 `/completion` に `cache_prompt=true`、同じ slot 0 を指定した。label は raw grammar（15ラベル）、JSON は JSON schema で出力を制約する。cache されるのは固定 prefix の計算済み状態であり、各発言は毎回完全な prompt に含めて判定する。回答の使い回しは行わない。最終の全9項目への復元と既存の schema・操作検証は従来どおり Bridge 側で行う。

## 結果

| 構成 | cache_prompt | 中央値 (ms) | p95 (ms) | 一致 | schema | 禁止移動 | 1500ms以内 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ollama compact baseline | 明示指定なし | 324.174 | 384.013 | 37/40 | 40/40 | 0 | 40/40 |
| native JSON、cacheなし | off | 314.559 | 340.736 | 37/40 | 40/40 | 0 | 40/40 |
| native JSON、cacheあり | on | 182.424 | 201.270 | 37/40 | 40/40 | 0 | 40/40 |
| native label、cacheなし | off | 229.630 | 239.565 | 36/40 | 40/40 | 0 | 40/40 |
| native label、cacheあり | on | 106.321 | 111.298 | 36/40 | 40/40 | 0 | 40/40 |

cache ありの llama.cpp では、JSON 構成の中央値 `cache_n=564`、label 構成の中央値 `cache_n=526`、毎回の prompt token は55だった。cache なしでは JSON の `cache_n=0` 相当で prompt は中央値619、label は581だった。decode token は JSON が中央値7、label が2（EOSを含む）。短いラベルは出力 token を減らすが、この既知ケースでは一致率は JSON 37/40、label 36/40だった。

全構成で schema 適合40/40、判定期限内40/40、禁止移動提案0件だった。これは契約と安全拒否の回帰結果であり、自然言語の意味判定が全件正しいことや実ゲームの動作を保証するものではない。

## 起動と比較

`Test-LocalLLM-Labels.bat` を開くと、サーバーの準備と warmup 後に日本語を入力して試せる。終了は `/exit`。身体は動かない。従来の `Test-LocalLLM.bat` も利用できる。両 launcher の `Prepare` は相手の所有確認済みサーバーを停止してから起動する。この相互切替とコンソール入力・終了を実機確認した。

Bridge 用の設定例は `Runtime/Config/llama-intent.example.json`。同じ native サーバーで JSON 判定を選ぶには `localIntentFormat` を `compact` にする。cache は `localIntentCachePrompt` で切り替える。

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_llama.ps1 Prepare
powershell -ExecutionPolicy Bypass -File tools/local_llama.ps1 Status
.\.venv-bridge\Scripts\python.exe -B tools/benchmark_local_intents.py --provider llama_cpp --local-format label --cases artifacts/local-llm/label-cache-cases.json --split all --timeout-ms 1500
.\.venv-bridge\Scripts\python.exe -B tools/benchmark_local_intents.py --provider llama_cpp --local-format label --cases artifacts/local-llm/label-cache-cases.json --split all --no-cache-prompt --timeout-ms 1500
powershell -ExecutionPolicy Bypass -File tools/local_llama.ps1 Stop
```

JSON と label、cache on/off の結果は `artifacts/local-llm/evaluations/label-cache-{ollama-baseline,json-off,json-on,label-off,label-on}` に保存している。latency は判定開始から完全な出力の解析・既存 intent 検証までで、nearest-rank percentile である。warmup は集計対象外で、5/40件は全構成共通の決定的な高速判定を通る。RTX 4070 Laptop GPU 上での逐次実行であり、初回の準備時間は表の定常時測定と異なる。最終コンソール確認の新規セッション初回は479.2msだった。

native は `artifacts/local-llm/ollama-v0.34.0/lib/ollama/llama-server.exe` に同梱された llama.cpp build `0f3a71be1` と CUDA 13 backend を明示して起動する。`tools/local_llama.ps1` は port 11436、`CUDA0`、1 slot、モデル固有の owner record を使う。ggml-org の b10809 は Ollama 用 GGUF metadata と一致せず起動に失敗したため採用していない。モデル自体は変更していない。

cache_prompt と grammar の仕様は [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) を参照する。関連する単体テスト89件が成功した。短ラベル版の不一致4件はすべて確認待ちとなった。

ゲームの `local.json` は変更していない。実音声、Unity、Brain 同居、実API、ユーザーの体感遅延は未測定であり、この比較をゲーム全体の完成判定へ読み替えない。コミットは実施していない。
