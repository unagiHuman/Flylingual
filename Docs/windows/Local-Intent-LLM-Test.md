# ローカル LLM 操作意図テスト

GPT-Live の会話経路を維持したまま、操作意図の判定だけを Windows 上のローカル LLM に置き換えて比較する。Responses は既定のまま利用でき、ローカル判定は明示的に選択した場合だけ使う。失敗時にクラウドへ自動再試行しない。Unity、Brain、音声認識、身体の操作はこの評価に含めない。

## 現在の判定構成

短ラベル制約生成と共通 prompt cache の追加実測・起動方法は [短ラベル・cache 評価](Local-Intent-Label-Cache-Test.md) を参照する。`Test-LocalLLM-Labels.bat` で追加構成を試せる。

確定した短い操作は既存の `fast_intents` を先に再利用する。LLM の出力は操作種類を表す `c` だけで、時間・距離・継続は入力から `ground_compact` が確定する。結果は既存の9項目の intent 形式へ復元し、既存の schema と操作検証を通す。この分離で、モデルが数量や実行期限を勝手に変更しないようにする。

既定の provider は `responses` のままで、`Runtime/Config/local.json` は変更していない。ローカル用の例は `Runtime/Config/local-intent.example.json` にあり、compact 判定の timeout は 1500 ms である。ゲーム側で選ぶ場合はこの例の conversation 項目を既存 local.json へマージして Bridge の次回起動に適用する。full 形式は従来の比較用に残し、`--local-format full` で測定できる。

## Windows での準備と実行

手軽に試すにはリポジトリ直下の `Test-LocalLLM.bat` を開く。サーバーの準備後、日本語の文を入力すると操作JSONと判定時間を表示する。身体は動かず、入力はファイルに保存しない。各文は実行中の操作がない状態で判定する。終了は `/exit`。モデルの解放には下記の `Stop` を使う。

Flylingual リポジトリ直下の PowerShell で実行する。ローカルサーバーは `http://127.0.0.1:11435` を使い、Ollama 0.34.0 と qwen3.5:4b が導入済みである。

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_llm.ps1 Prepare
.\.venv-bridge\Scripts\python.exe -B tools/benchmark_local_intents.py --split dev --timeout-ms 1500
.\.venv-bridge\Scripts\python.exe -B tools/benchmark_local_intents.py --split holdout --timeout-ms 1500
```

`Prepare` はローカル判定用の準備とモデルのウォームアップを行う。compact は `keep_alive=-1` で評価中のモデルを保持し、full は従来の keep-alive 10 分を使う。評価終了後は、所有確認をした同じ launcher から停止してモデルを解放する。

```powershell
powershell -ExecutionPolicy Bypass -File tools/local_llm.ps1 Status
powershell -ExecutionPolicy Bypass -File tools/local_llm.ps1 Stop
```

サーバーの実体、PID、開始時刻、評価結果は `artifacts/local-llm/` に保存する。各評価の `results.jsonl` は入力・判定・失敗・所要時間、`summary.json` は集計、`metadata.json` はモデル、設定、ソースと fixture の hash、GPU 情報を記録する。既存の出力先は上書きしない。

## 評価 fixture と判定

通常の比較には `tools/fixtures/local_intent_cases.json` を使う。dev と holdout は各12件で、調整後の結果と最終未使用 holdout の結果を混同しない。追加の最終 fixture は `tools/fixtures/local_intent_final_holdout.json` の16件で、最終条件を固定してから初めて評価した。

評価では JSON の契約適合、期待した意味、移動禁止ケースでの移動提案、タイムアウトを分けて集計する。質問・曖昧入力・安全規則の変更要求は移動を提案してはならない。入力文は試験用であり、結果に保存される。

## 実測結果

実測原本は次のディレクトリに保存している。

- `artifacts/local-llm/evaluations/grounded-regression-01`: 24/24、一致率100%。同じ24件の初回 full 判定は 1.941 秒だったが、compact は中央値 321.427 ms、p95 371.369 msで、約6倍短縮した。
- `artifacts/local-llm/evaluations/grounded-additional-regression-01`: 22/24。中央値 329.789 ms、p95 370.75 ms。2件は clarify 判定となった。
- `artifacts/local-llm/evaluations/grounded-final-holdout-01`: 最終未使用16件を各3回、48測定。39/48（13/16）、中央値 329.970 ms、p95 364.586 ms。3発言は全試行で clarify、移動禁止ケースの移動提案0件、タイムアウト0件、判定期限1500 ms。
- `artifacts/local-llm/evaluations/grounded-final-holdout-02`: 未知単位の併記と half a second の境界修正後、同じ16件を3回再確認。39/48、中央値333.915 ms、p95 370.437 ms。全48件が1500 ms以内、禁止移動0件。ソースhashを含む最終版の記録はこちら。再確認なので新たな未使用評価とは数えない。

24件の回帰満点は調整済みケースの結果であり、最終 holdout の81.25%とは別の指標である。いずれもローカル intent 判定の測定で、ゲーム全体の完成や体感遅延を示すものではない。

対話コンソールの単発確認では「右側は危ない？」が648.1 msでquestionになった。上記の約330 msは連続したウォーム評価の中央値であり、毎回の応答時間を保証しない。待機後やGPU負荷による変動は別途評価する。

## 未測定と残課題

実音声、Unity、Windows Brain の同居、実際の身体操作、GPT-Live／Responses との E2E は未測定である。したがって「ゲーム全体が完成した」「体感0.3秒」とは扱わない。英語引用の後に続く依頼、時計回りなどの言い回しでは clarify が残っているため、次のモデル調整の対象とする。

操作入力を conversation 側で一本化する変更は別作業であり、この評価結果には含めない。課金 API はこの手順で実行しない。

契約・数量・設定・即時判定の純粋な翻訳テスト69件は合格。これは Unity、実 Brain、実 API の合格とは別である。

```powershell
.\.venv-bridge\Scripts\python.exe -B -m unittest tools.test_persistent_intent_translation tools.test_intent_interpreter tools.test_local_intent_config tools.test_fast_intents tools.test_compact_local_intent
```

公式仕様：[Ollama Chat API](https://docs.ollama.com/api/chat)、[Windows](https://docs.ollama.com/windows)、[qwen3.5:4b](https://ollama.com/library/qwen3.5:4b)、[固定した配布版](https://github.com/ollama/ollama/releases/tag/v0.34.0)。
