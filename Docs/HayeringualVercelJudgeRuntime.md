# Hayeringual Vercel Judge Runtime

更新: 2026-09-14。最新の提出候補・受入れ状態は [提出前レビュー対応](windows/PreSubmission-Review-Response.md) と本書末尾のレビュー対応節を参照。以下のJudge最終Player／配布ZIPの記録はレビュー対応前の歴史的実績であり、最新候補の合格証拠ではない。Judge最終Playerで実Cloud返答と実Brain移動・停止を確認し、Windows配布ZIPを作成した。Dev／DemoのLocal実Brain操作も確認済み。Vercel実翻訳20件は全成功、P50=1037ms、P95=1469ms。**仕様全項目の完成判定は未達**。active keyのbudget／期限、別PCのclean-machine受入れ、OS全体のネット切断試験が未確認である。

## 1. 既存調査と最終経路

Unity実検証版6000.5.9f1。package lockの自動解決でBurst1.8.29→1.8.30、Searcher4.9.4→4.9.5を採用し、その実版で検証した。Unityの `ConversationSessionController` が同居Bridgeへ入力を送り、`Runtime/Bridge/server.py` → `intent_interpreter.interpret_intent` が操作意図を判定する。既存Local経路は `fast_intent`、llama.cpp/Ollama、必要に応じたOpenAI Responses。`local_intent.py` のコード分類・量の根拠付け・展開、既存admissionとAction/Plan実行を再利用した。

```text
Unity テキスト入力
  → 同居Bridge / interpret_intent
    → Fast Rule（明白な操作）
    → Local: llama.cpp等 / Cloud: cloud_intent.request_cloud
                                  → 自前Vercel /api/fly/translate
                                  → AI Gateway → Gemini
    → ground_compact / expand_compact / validate_intent
    → 既存Action/Plan → Windows MaleCNS → BrainFrame → Unity PhysX
```

新しい神経シミュレーターやmotor生成は追加していない。Cloudは翻訳だけを担当する。GPT Liveの声・マイク・Realtime構造は置換していない。今回のCloud構成は**テキスト入力と短い字幕応答**を使用し、配布物へOpenAI keyを必要としない。Dev/Demoの既存GPT Live経路は維持される。

## 2. 追加・変更ファイル

| 区分 | ファイルと役割 |
|---|---|
| 追加 | `backend/hayeringual-api/` Next App Router、schema/prompt、AI SDK client、エラー正規化、単体試験、lockfile、README、実測script |
| 追加 | `Runtime/Bridge/cloud_intent.py` 認証情報を送らないCloud HTTP transport |
| 変更 | `Runtime/Bridge/intent_interpreter.py` 既存provider境界へvercel追加 |
| 変更 | `Runtime/Bridge/config.py` 設定検証、`Runtime/Bridge/server.py` 等のテキスト会話統合 |
| 追加 | `Runtime/Config/judge.example.json`、`judge-native.example.json` 配布設定例 |
| 追加 | `UnityProject/Assets/RuntimeIntegration/PlayScreen/Editor/HayeringualBuildWindow.cs` 独立channel/provider選択 |
| 変更 | `tools/windows_native.py`、`ConversationNativeBootstrap.cs` ビルド選択の起動反映 |
| 追加 | `tools/package_judge.py` portable Python・Bridge・Brain・必要データの同梱 |
| 追加 | `tools/prepare_judge_python.ps1` portable CPython取得・固定依存導入・配布元hashと依存版の記録 |
| 追加 | `tools/test_cloud_intent.py`、`tools/test_package_judge.py` transport/配布境界試験 |

完全な変更一覧は統合後のGit差分を正本とする。生成物と秘密情報はcommit対象外。

## 3. Local/CloudとDev/Demo/Judge

Editorメニュー `Flylingual > Build Channels > Configure Windows Build` で選ぶ。

| Channel | Development Build | 初期Provider |
|---|---:|---|
| Dev | ON | Local |
| Demo | OFF | Local |
| Judge | OFF | Cloud |

Provider欄は独立して変更可能で、Dev+Cloudも選べる。`Debug.isDebugBuild` では選択しない。出力先は `artifacts/hayeringual-builds/<Channel>-<Provider>/`。`build-channel.json` の `channel/provider/backendUrl` をnative launcherが読み、生成した実行用Bridge設定へ反映する。

Localは `conversation.intentProvider=llama_cpp`。Cloudは `vercel`、`cloudIntentUrl` に自前backendの `/api/fly/translate`、timeout5000ms、Responses fallback無効、conversation mode=textとなる。細かい既存Local設定は保持する。**Localの意図判定がローカルでも、GPT LiveやResponsesを有効にしたDev/Demoの音声会話全体はネット接続を必要とする。**

## 4. Backendと環境変数

Vercel projectのRoot Directoryを `backend/hayeringual-api` にする。Node >=22（実検証24.13.1）。インストール版は ai7.0.99、Next16.3.5、React19.3.0、Zod4.6.5、TypeScript7.0.2。`npm ci`、`npm run typecheck`、`npm test`、`npm run build`。`npm run dev` はlocalhostへbindする。

| 環境変数 | 初期値・意味 |
|---|---|
| `AI_GATEWAY_API_KEY` | backendだけに保存するJudge専用key。値はこの文書に記載しない |
| `HAYERINGUAL_LLM_MODEL` | `google/gemini-3.5-flash-lite` |
| `HAYERINGUAL_REASONING` | `minimal` |
| `HAYERINGUAL_MAX_OUTPUT_TOKENS` | 96（許容32–128） |
| `HAYERINGUAL_TIMEOUT_MS` | 4000（許容100–4000） |
| `HAYERINGUAL_LOG_LEVEL` | info、offで診断抑止 |

現行SDK typingsで `generateText({output: Output.object({schema}), reasoning:'minimal'})` を確認済み。Gateway `sort:'ttft'`、provider固定なし、SDK retry0。ゲームはCodex用endpointを使用しない。[AI SDK reference](https://ai-sdk.dev/docs/reference/ai-sdk-core/generate-text)、[Gateway provider routing](https://vercel.com/docs/ai-gateway/models-and-providers/provider-options)。

実APIでは統一`reasoning:'minimal'`だけでは96token枠のうち89tokenをreasoningに使い、length終了でstructured outputが成立しなかった。Google固有の`thinkingConfig: {thinkingLevel:'minimal', includeThoughts:false}`とJSONだけを返す短文指示を追加した後、20件全成功した。modelは`google/gemini-3.5-flash-lite`、maxOutputTokens96、retry0を維持している。

## 5. Vercel設定とデプロイ

Vercel team `isaosan`、project `hayeringual-api` を作成し、Productionを [hayeringual-api.vercel.app](https://hayeringual-api.vercel.app) へ公開済み。Judge専用 `hayeringual-judge` keyを、上限$10（CLI `--limit 10`）、refreshなし、期限30日で作成し、Preview／Productionの環境変数へ設定した。秘密値はソース・配布設定・この文書に記載しない。Gateway budgetはsoft capで、厳密な最終請求上限ではない。BYOKを使う場合はGateway予算の対象条件を別途確認する。

現在の実endpointは `https://hayeringual-api.vercel.app/api/fly/translate`。EditorのApplication backend欄とpackage scriptの `--endpoint` へ指定する。Production health200と、下記修正後の実翻訳成功を確認した。環境変数の変更後は再デプロイする。設定例の `https://example.vercel.app/api/fly/translate` はplaceholderのままである。

初回は統合担当が [Gateway管理画面](https://vercel.com/isaosan/~/ai-gateway) で「Add a Card」未完了を実見し、SDK診断は`GatewayInternalServerError`、upstream403、`BillingOrCredits`だった。その後ユーザーが外部ファイルで提供した別keyを、明示許可を得てPreview／Production Secretへ設定した。getCreditsで約$4.95の残高を確認し、認可は解消した。秘密値と提供ファイルの内容はこの文書に記載しない。

**現在のactive keyのbudget／expiryは未確認。** ユーザーは発行元を`isaosan`と回答したが、CLI／UI一覧には旧作成key1件しかなく、提供keyと一致しない。先に作った`hayeringual-judge`の$10・refreshなし・30日期限は旧keyの設定であり、現在は未使用。したがってCost要件は未達とする。カード登録待ちではなく、稼働中keyの上限・期限を確認する段階である。

## 6. HTTP契約と失敗動作

`GET /api/health` は固定の `{ok:true,service:"hayeringual-api",version:"1"}`。モデルへの接続可否は表さない。

`POST /api/fly/translate` はschemaVersion1、playerInput最大1000文字、language ja/en、flyStateとして既存compact_contextのactive/candidate/activeForward/activeNudge/defaultMs/maxMsだけを受け取る。任意observationはfresh、forward/turn（有限値±1000またはnull）、bodyMovementVerified=false。神経decoder出力は身体運動確認ではなく、古い値とnullは現在不明として扱う。

応答は `{schemaVersion:1,c:<既存15コード>,speech:<160文字以内>}`。Actionの時間・距離・権限をモデル出力へ任せない。未知propertyを拒否し、受信bodyはContent-Lengthに依存せず16KiBまで、出力を再検証する。

不正入力400、body超過413、content-type不正415。Gateway402、通信障害、timeout、不正モデル応答は503 `CloudUnavailable` に正規化し、生のprovider errorをUIへ返さない。Bridgeは最大5秒、redirectなし、レスポンス4KiB上限で検証する。キャンセルを伝播し、古い操作を再送しない。Cloud失敗時はclarifyと短い案内を返す。明白な「前進・右・左・停止」は既存Fast Ruleで扱えるため、ネット失敗を新しい移動判断に変換せず操作待受を維持する。

## 7. Windows Judgeパッケージ

Unity PlayerだけではBridge/実Brainが足りない。Judge-Cloudをbuildした後、依存入りportable CPython（venv不可）を用意して、repoルートから次を実行する。

```powershell
powershell -File tools/prepare_judge_python.ps1
python tools/package_judge.py --output artifacts/hayeringual-builds/Judge-Cloud --python-root artifacts/judge-python/portable --endpoint https://hayeringual-api.vercel.app/api/fly/translate
```

portable Pythonにはnumpy、numba、llvmlite、psutil、aiohttpが必要。scriptは既存Unity exeを確認し、Bridge/Brain allowlist、必要なgraph配列、校正設定、atlas、portable Pythonを同梱し、相対パスのjudge.json/judge-native.jsonとSHA256 manifestを作る。開発用local設定、venv、API key、ローカルLLMモデルは同梱しない。既存Runtimeがある出力へ重ねて実行せず、新しいbuild先を使う。

準備scriptは開発者側の`uv`を使い、python.orgのCPython 3.11.9 Windows amd64 embeddable配布を取得する。numpy1.24.3、numba0.61.2、llvmlite0.44.0、psutil7.2.2、aiohttp3.14.3を固定指定し、import確認後にアーカイブSHA256と実際の依存版を`distribution-manifest.json`へ記録する。既存Destinationを拒否するため、再準備は`-Destination`で新しい場所を指定する。審査員はこのscriptやuvを実行しない。

組立済みRelease Playerは `artifacts/hayeringual-builds/Judge-Cloud/FlylingualConversation.exe`。embedded Pythonの`_pth`にはpackage rootを`../../`と末尾スラッシュ付きで指定する。Windowsのembed環境で裸の`../..`では意図したrootに解決されなかった実測に基づく。`-B -I`でBridge server、tools/dev、windows_native、brain_server_bridgeの推移的import確認が成功した。この確認ではBrainを起動していない。

最終候補は別出力 `artifacts/hayeringual-release/Judge/` に組立済みで、Cloud URLは実Production aliasを設定した。配布候補ZIPは `artifacts/hayeringual-release/Hayeringual-Judge-candidate.zip`、196,960,905 bytes。manifest2253ファイルのSHA256は全一致し、ログ・生成cacheをZIPから除外した。最終候補と下記の旧`Judge-Cloud`出力で実施したoffline試験は別の証拠として扱う。

Dev+LocalとDemo+Localのビルドも成功した。DemoのBuildReportは`Succeeded`、`options=None`。`errors=1`はPipeline制御要求の5000ms timeoutで、compile errorは確認されていない。Dev+Local実Brain試験は`control_pass`、変位3.0406、sequence20→100、fresh=true、ready=false、Live=true。`old_conversation_generation`表示は残課題である。Demo最終試験は[`demo-local-final/result.json`](../artifacts/judge-validation/demo-local-final/result.json)で`control_pass`、error空、Live=true、sequence15→107、変位3.003661を確認した。

Bootstrapがbuild選択を探す場所は、誤った`AppDomain.BaseDirectory`から`Application.dataPath`の親へ修正した。Judge-v2で実行用`runtime-bridge.json`の生成とCloud設定の反映を実見した。package endpointが古いbuild選択に上書きされる問題も修正済み。

**レビュー対応前の配布ZIP（歴史的記録。最新提出候補ではない）**は [`Hayeringual-Judge-Windows.zip`](../artifacts/hayeringual-release/Hayeringual-Judge-Windows.zip)、196,961,039 bytes、SHA256 `bcd3c7a4c1621efca163b3ce11a95f97172ddfd2c1a9afbae8c2c7023e8db5e8`。2253ファイルのmanifest hash一致と限定credential scan合格を確認し、ログ／cacheを除外した。旧candidate ZIPと区別する。Brainソース・校正config・4graph配列の原本hashは[`Judge-v2/judge-manifest.json`](../artifacts/hayeringual-release/Judge-v2/judge-manifest.json)で確認できる。

「Pythonをユーザーにインストールさせない」はportable runtimeを同梱して達成する。実Brain用データも必要なので、小さいUnity exeだけの配布とは異なる。フォルダ全体を移動した環境でexeから起動し、Unity Editor・Ollama・既存Pythonなしの受入れを別途実施する。

## 8. 検証・性能・セキュリティの現状

| 項目 | 証拠または残gate |
|---|---|
| Backend単体 | 11件合格。schema、未知フィールド、body上限、402、不正出力、deadline、cancel、コードparity、observation等 |
| Backend型/build | `npm run typecheck` 成功、`npm run build` 成功 |
| Backend実HTTP | built server localhost3217でhealth200、不正POST400を確認、試験server停止済み |
| Local/Cloud Bridge試験 | 関連105件合格。単体・transport試験であり実Cloud成功の代替ではない |
| Windows Judge/offline | 最終PlayerのCloud返答＋実Brain移動／停止が`control_pass`。先行失敗時fallback試験も別に合格 |
| 実Gateway | 現keyの認可解消、Google思考設定と短文指示修正後に実翻訳20件全成功 |
| Cloud P50/P95 | 成功20件、P50=1037ms、P95=1469ms、min=869ms、max=1584ms、error0。P95目標達成、P50<1秒は未達 |
| active keyの予算 | 発行元・budget・expiry未確認。旧専用keyは現在未使用でCost要件は未達 |
| clean-machine | 未実施。開発PCで起動できるだけでは代替できない |
| セキュリティ | backendにkey環境変数のみ、Unityは自前URLのみ。配布configにcredential欄を拒否、child環境から秘密変数を除去。候補のsource/JSON/Python/text/DLLの資格情報形式scanは合格。第三者site-packagesはscan対象外であり、全バイナリの不存在証明ではない |

実API測定はbackendディレクトリから `npx tsx scripts/benchmark.ts https://<YOUR-PROJECT>.vercel.app 20`。healthとschemaを検査し、全試行と成功試行を分けてP50/P95/min/max、error countをJSON出力する。20～100件の逐次実リクエストで通常の課金が発生する。成功0件なら成功レイテンシーはnull。目標P50<1秒、P95<2秒は保証ではない。

初回の [`cloud-benchmark.json`](../artifacts/judge-validation/cloud-benchmark.json) は20件全失敗で、P50=262ms／P95=544msは失敗応答時間だった。修正後の [`cloud-benchmark-final.json`](../artifacts/judge-validation/cloud-benchmark-final.json) は20件全成功、P50=1037ms／P95=1469ms／min=869ms／max=1584ms。二つの試験を混ぜず、後者を当時の成功性能として扱う。最新候補の性能保証へ拡張しない。

packageのbackend URL反映不具合も修正した。関連package試験6件を含む合計105件が最終実行で合格した。

### 実Brainを使ったCloud接続失敗試験

同じWindows開発PC上のRelease Judge Playerをisolated portable Pythonで実行し、Cloud接続先を到達不能な`.invalid`ドメインにした試験。OS全体のネットワーク切断、別のclean machine、ゲームのクリア確認は行っていない。

| 観測 | 結果 |
|---|---|
| Brain接続 | `127.0.0.1:18766`、`MALECNS_EXPERIMENTAL` |
| Brain ready / fresh | `false` / `true`。readyを昇格しない |
| BrainFrame sequence | 9 → 79 |
| 身体の変位 | 2.7030234336853029 Unity単位 |
| Cloud fallback / STOP | `true` / 成功 |
| 試験判定 | `control_pass`、errorは空 |

証拠は [`result.json`](../artifacts/judge-validation/offline/result.json) と [`player.log`](../artifacts/judge-validation/offline/player.log)。Player logには正式シーン開始、6脚地形処理の準備、sequence79での`NATIVE_BODY_STOP`と終了処理を記録している。確定済み [`bridge.log`](../artifacts/hayeringual-builds/Judge-Cloud/artifacts/judge-runs/3e40c3c64fdb4ca7af1b27f59c0dc228/bridge.log) は実Brain起動約3703ms、controller数1での接続、明示release後0を記録し、同runの`status.json`は`stopped`。これらはCloud失敗時にも実Brain経由で操作が続いた証拠であり、Vercel翻訳成功の証拠ではない。

### 最終候補の実Production alias試験

認可解消前の候補Playerを実Production aliasへ接続した [`cloud-player/result.json`](../artifacts/judge-validation/cloud-player/result.json) も`control_pass`。変位2.76894、sequence9→89、fresh=true、Brain ready=false、STOP成功、cloudFallback=trueを確認した。`cloudReplyReceived=false`であり、上流403によりCloud翻訳応答は受信できていなかった。この試験は上の`.invalid`接続失敗試験とは別で、実サービスの課金条件エラー時にも操作を続けられた確認である。モデル翻訳・Cloud会話成功としては扱わない。

### Judge最終Playerの実Cloud成功

認可とモデル出力設定の修正後、[`judge-final/result.json`](../artifacts/judge-validation/judge-final/result.json)で`control_pass`を確認した。`textSession=true`、`live=false`、error空、`cloudReplyReceived=true`、`cloudFallback=false`。Windows実Brain `127.0.0.1:18766`／`MALECNS_EXPERIMENTAL`でfresh=true、ready=false、sequence11→104、変位2.977624、STOP成功を観測した。実Cloud返答とBrainFrameを介した身体操作の成功を確認したが、ゲーム全編クリアや別PCでの動作を意味しない。

## 9. トラブルシュートと残課題

- healthは成功して翻訳503: keyの環境scope、budget/expiry、model名、再デプロイを確認する。health成功をモデル成功と混同しない。
- 400: schemaVersion、6項目のcontext、型、未知propertyを確認。raw neural dataは送らない。
- Player起動失敗: package全体、portable依存、graph/config/atlas、localhost18766、同居Bridgeの所有process logを確認する。実Brainへ別probeを追加接続しない。
- Cloud遅延: backendのrequest ID/model/latency/status/timeoutを確認し、実20件で測る。無限retryや会話履歴増大で解決しない。
- Judgeで声が出ない: 今回のCloudはtext mode。Dev/DemoのGPT Live設定と区別する。

active keyのbudget／expiry、別PCのclean-machine、OS全体のネット切断でのoffline受入れが残gate。配布v2実Player・ZIP、Demo最終確認、実Cloud翻訳と20件性能計測は完了し、同PCの到達不能endpoint試験は上記の限定条件で合格。Devの`old_conversation_generation`表示も残す。旧専用keyの予算設定を現在のkeyへ読み替えない。Streaming、別モデルfallback、高度rate limiting、WebSocketは未実装の任意P2。基本的な公開WAF rate limitは下記レビュー対応で反映済み。

## Local LLMの最終限定回帰

既存llama.cpp（127.0.0.1:11436、qwen3.5:4b、label・cache有効）に既知ケース先頭10件を実行。schema10/10、期限内10/10、意味一致9/10、禁止移動提案0。全試行P50=107.192ms／P95=111.767ms。うちLLM経路7件のP50=109.092ms、決定的経路3件。1件不一致のためbenchmark終了値は1であり、全項目合格とはしない。これはテキスト分類だけの限定回帰で、ゲームE2Eや独立holdoutではない。結果: [local-llm-final](../artifacts/judge-validation/local-llm-final)。

不一致のdev-05（右側に寄って進んで）は、既存label-cache-label-on結果と同じくモデルが左右を誤分類し、Bridgeがclarifyへ拒否した。今回の10件内では新たな意味判定退行を認めていない。

## 2026-09-14 提出前レビュー対応

最新候補のbuild/hashおよびcold/warm・ゲーム受入れの確定結果は [PreSubmission-Review-Response](windows/PreSubmission-Review-Response.md) を正本とする。旧ZIPや過去PlayerのPASSを最新候補へ転記しない。通し試験はユーザーが後日人手で行う方針。

公開WAFはCLI 59.16.0で未設定を確認後、`POST /api/fly/translate` だけを対象とするIP単位120 requests/60秒の `fixed_window` ルールを本番反映した。超過時は `rate_limit`、ブラウザchallengeは使用しない。反映後はEnabled、active rule 1件。health 200、不正POST 400を確認した。閾値到達の負荷試験は未実施で、共有IPの同時利用や厳密な請求上限を保証するものではない。原本: [firewall-review.json](../artifacts/submission-20260914/firewall-review.json)。

実Cloudへの「こんにちは」はHTTP 200、返答あり、約2,297msだった。これは1件のsmoke確認であり、P50/P95やゲーム全体の受入れではない。原本: [cloud-smoke.json](../artifacts/submission-20260914/cloud-smoke.json)。

ユーザー提供の稼働keyをメモリ内だけで使用し、`/v1/credits` で残高 `901.26050001` を2026-09-14 14:03:54 UTCに確認した。秘密値はログ・配布物へ記録していない。credits endpointからbudget/expiryは取得できず、両者は依然未確認。残高を専用keyの予算上限や有効期限と読み替えず、旧keyの$10/30日設定も流用しない。原本: [gateway-credits.json](../artifacts/submission-20260914/gateway-credits.json)。

FastRuleのbare「前進」/`forward`/`right`/`left`登録欠落を修正した。429/503後も8つの基本操作語は追加Cloud呼出しなしで処理されることを純粋テストで確認し、パッケージ関連を含む26テストがPASS。これは実際にWAF閾値を超えた負荷試験の代替ではない。Judge-Cloudの配布READMEは日英のテキスト操作版・Live音声なしを明記している。
