# 提出前レビューへの対応（2026-09-14）

レビュー固定版は `9e2dd6c9cd43da5ff8187d0d6357a912512f68ce`、今回作業の基準は `71fca65`。必須ファイル欠落のP0は修正し、候補ZIPの同梱・展開整合を確認した。これは全体の提出受入れ完了を意味しない。同PCの展開ZIPによる実Brain試験と、人間の操作・別PC・実マイクの受入れを別管理する。

## 最終候補v3

[Flylingual-Judge-Windows-20260914-v3.zip](../../artifacts/submission-20260914-v3/Flylingual-Judge-Windows-20260914-v3.zip)、175,473,925 bytes。SHA-256 `5a96849363e77b309900ce926876a7befed3768fd4236d64737744cf609dd046`。Judge / vercel / text、Release options=None、Unity6000.5.9f1。2026-09-14 14:24:52–14:25:12 UTCのBuildReportはSucceeded。記録されたerrorはPipeline要求の5000ms timeoutであり、ビルド失敗ではない。

manifest 2,257件は元フォルダ・ZIP展開先で全一致。原本は[archive-receipt.json](../../artifacts/submission-20260914-v3/archive-receipt.json)と[source-build-receipt.json](../../artifacts/submission-20260914-v3/source-build-receipt.json)。後者は基準commitと901ソースファイルのhashを保存する。作業ツリーにある別作業の未commit変更もビルドに含まれるため、今回の修正commit単独とDLLが一致するとは記載しない。

ユーザー指示により、通し試験は後日人手で実施する。v3では起動・基本操作・回避・被弾後リトライ・終了・再起動に検証を限定し、全コース合格を推定しない。

## v3の実配布物検証

| 確認 | cold（キャッシュなし） | warm（同じ展開物を再起動） |
| --- | --- | --- |
| 同梱Python isolated import/config | PASS | PASS |
| タイトル開始、前進・左右・STOP・再移動 | PASS | PASS |
| 警告→実移動回避、停止→実被弾 | PASS | PASS |
| 実ゲームオーバーUI→リトライ→再移動・STOP | PASS | PASS |
| Probe / runner判定 | submission_path_pass / pass | submission_path_pass / pass |
| Action gate | 12/12 | 12/12 |
| Numba cacheファイル数 前→後 | 0→4 | 4→4 |
| BrainFrame sequence | 8→454 | 6→519 |
| epoch 初期→リトライ後 | 5→18 | 5→23 |
| ready / 最終fresh / 最終error | false / true / 空 | false / true / 空 |
| 試験wall / probe秒 | 95.219 / 86.274 | 127.843 / 120.139 |
| 最大サンプル合計process RSS bytes | 1,200,463,872 | 1,163,210,752 |
| Player Exception / exit code | 0 / 0 | 0 / 0 |
| 強制cleanup / 残存所有PID | 不要 / なし | 不要 / なし |
| 終了後ポートbind確認 | PASS | PASS |

原本: [cold](../../artifacts/submission-20260914-v3/validation/cold/runner-summary.json)、[warm](../../artifacts/submission-20260914-v3/validation/warm/runner-summary.json)。wallは試験全体でありBrain単窓の計算時間ではない。RSSはprocessを定期サンプルした合計で、共有ページを重複計上し得る。両runの開始前TCP解放待機は0.015秒/0秒。

同PCのWindows 11、通常ユーザー環境で実行。同梱CPython3.11.9、numpy1.24.3、numba0.61.2、llvmlite0.44.0、psutil7.2.2、aiohttp3.14.3。Brain `127.0.0.1:18766` / `MALECNS_EXPERIMENTAL`、Bridge8770/control8771。ready=falseをそのまま保持する。各action gate内のepoch同一とfresh/sequence進行を検査し、ゲームオーバー・再開でのepoch変化を「接続不変」と説明しない。Cloud自由文はこのprobeの対象外で、上記の別HTTP smokeと区別する。

- Brain source hash: `0e84a23bf81da21a9f514977737e2652425375df08778dfd3d6a23acd1544b0f`
- graph hash: `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`

再実行は未使用の出力先を指定する。runnerは配布外の開発用Pythonから起動するが、import/configとゲーム内部のBrainは同梱Pythonを使い、Playerへ開発repoRootを渡さない。

```powershell
.\.venv-bridge\Scripts\python.exe tools/verify_judge_package.py --package artifacts/submission-20260914-v3/Extracted/Flylingual-Judge --output artifacts/judge-verification-new --mode submission
```

## 後日・人手で確認する事項

- [ ] 同じv3 ZIPで落下→ゲームオーバー→リトライ→操作再開。
- [ ] 通常操作だけでゴールまで完走。ユーザー指示により自動通し試験は追加しない。
- [ ] 実GPT-Live音声版で人間のマイクを使い、日英の主要操作・台本中の割込み・STOPと音声デモ収録。
- [ ] 別PCでの初回起動。今回のcoldはNumba cacheなしの意味であり、既存PlayerPrefsにより初回説明UIは表示されていない。
- [ ] 稼働キーのbudget/expiryを管理画面で照合。残高・旧キー・WAF設定から推定しない。

## 確定した対応

| 指摘 | 対応と確認範囲 |
| --- | --- |
| 必須Brainファイル欠落 | `visual_threat.py` と `config/visual_threat_v1.json` をパッケージ対象へ追加。`_SOURCE_FILES` 全項目とASTによるimport依存閉包の回帰検査を追加。 |
| Judgeと音声版の混同 | 配布READMEを日英で整理。Judge-Cloudはキー不要のテキスト操作版であり、GPT-Live音声・マイクを提供する版ではないと明記。 |
| 基本操作とCloud障害 | FastRuleの「前進」/forward/right/leftの登録欠落を修正。429/503後も基本操作8語を処理し、追加Cloud呼出しがないことを検査。パッケージを含む関連26テストPASS。 |
| 公開Cloud濫用対策 | 公開WAFの未設定状態を確認後、下記の限定ルールを本番へ反映。稼働キーの予算・期限は未確認のまま区別。 |

## 先行候補（v1、最終候補ではない）

`artifacts/submission-20260914/Judge` はReleaseビルド（options `None`）。2026-09-14 22:52:51–22:53:27 JST（13:52:51–13:53:27 UTC）に `Succeeded`。同梱manifestは2,257ファイル。ZIPを別ディレクトリ `Extracted` へ展開し、manifestのhash一致を確認した。同一PCの別ディレクトリ検証であり、別PCやclean-machineでの確認ではない。

- ZIP: `Flylingual-Judge-Windows-20260914.zip`、175,470,224 bytes。
- SHA-256: `a303688d6668589cf41ccc7e385981de5bd5ac160c688a01e85f70e307479fc6`
- 原本: [archive-receipt.json](../../artifacts/submission-20260914/archive-receipt.json)。秘密情報検査はapplication Python/JSON/HTML/textを対象とし、全バイナリの完全保証ではない。

候補は作業ツリーからのビルドであり、基準commit単独からの再現物とは記載しない。既存の未commit変更（swatterの `initialGraceSeconds=60`、Title UI等）を含む。これらを今回の修正commitへ混入させず、候補のDLL hash等のprovenanceを保持して、ソースcommitと配布バイナリの一致範囲を区別する。

## 公開Cloudの確認

Vercel CLI 59.16.0で初期状態 `NotConfigured` を確認し、`POST /api/fly/translate` に限定したIP単位120件/60秒、fixed window、超過時 `rate_limit` のルールを反映した。ブラウザchallengeは使用しない。反映後はFirewall Enabled、active rule 1件、health 200、不正POST 400を確認した。

原本は [firewall-review.json](../../artifacts/submission-20260914/firewall-review.json)。閾値到達の負荷試験は未実施。会場の共有IPでは複数利用者が同じ枠を共有するため、通常利用を誤遮断しないことまで実証していない。管理一覧で確認できた旧キーは現稼働キーの予算証拠ではなく、提供されたキーで `/v1/credits` を確認し、2026-09-14 14:03:54 UTC時点の残高は901.26050001。秘密値は出力・保存していない。同APIはキーのbudget/expiryを返さず、その2点は未確認。WAFの反映を請求上限の保証としない。反映後の実テキスト「こんにちは」はHTTP 200、2297ms、返答あり（[cloud-smoke.json](../../artifacts/submission-20260914/cloud-smoke.json)）。残高原本は[gateway-credits.json](../../artifacts/submission-20260914/gateway-credits.json)。

## 先行候補v1の実配布物試験

| Gate | 結果 |
| --- | --- |
| 同梱Pythonによるcold起動 | PASS。cache 0→4、12 action gate合格、98.954秒、peak summed RSS 1,191,501,824 bytes |
| 同じ候補のwarm再起動 | 起動・主要操作は成立。ただし検証コードの回避判定が不正確で試験全体はincomplete。下記修正後にv2で再検証 |
| 通常タイトル→前進・左右・STOP・再移動 | PASS。初回説明は既存PlayerPrefsのため表示されず、初回利用者の検証とはしない |
| 警告→実移動回避、実被弾→ゲームオーバーUI→リトライ→fresh操作再開 | coldはPASS。warmも実ゲーム回避・被弾・リトライを観測したが、回避gateの誤判定を保持 |
| 通常操作による全コース完走 | 通しprobeの通知相関バグでincomplete。Brain適用・実移動は成立。修正版で再試験 |
| 終了後の所有process終了 | cold/warmでexit 0、強制cleanup不要、残存所有PIDなし、Player Exception 0 |

v1 coldはsequence 6→360、ready=false、fresh=true、backend `MALECNS_EXPERIMENTAL`。warm-v3はsequence 5→459、壁時間92.109秒。warm/warm-v2は実Player起動前にポート再利用検査で止まった。待受processはなくWindows TCP TIME_WAITを確認したため、runnerにTIME_WAITのみ最大90秒待つ処理を追加した。稼働serverを停止していない。

検証コードの修正: 回避はゲームが保持するidle anchorからの0.3mで判定するため、警告開始地点から0.3mを再要求しない。実ゲームのidle reset・非被弾と警告後の実変位を照合する。通しprobeでは`brain_applied`通知にepochがないため、epoch付き`submitted`を保存してrequestId/commandIdと現在のsession/instance/epoch/generationで照合する。ゲームの物理・コース・motorを変えて合格させる変更ではない。

実測原本の保存先は `artifacts/submission-20260914/validation`。進行中ログを結果として引用していない。追加probeは実Brain・PhysX・通常テキスト入力と実リトライUIを使い、診断teleport、collider無効化、固定motorによる代替を行わない。待機は実swatter設定から算出する。

物理マイク、人間の声による日英操作・割込み、実音声デモ収録、別PC起動は未実施。果汁接触を報酬学習、DNp01の窓実測を恐怖・主観的感情と説明しない。Judgeのテキスト体験とLive音声デモの検証を混同せず、残る受入れ結果と予算確認後に提出判断を行う。

## 先行候補v2の試験（最終候補ではない）

ZIP SHA-256 `66a0f35681202ad253e12599a03c26708c7109eafd3b45c37c1bd7de27f18cdb`、175,473,778 bytes、manifest 2,257件一致。原本は `artifacts/submission-20260914-v2`。

制限付き実行の`validation/cold`はPlayerPrefs保存時に例外となり、今回のPlayerだけを終了した。通常ユーザー環境の`cold-user`では同例外はなく、12 gate中11合格、回避gateだけが警告終了直後の0.0154mを採用して誤判定した。実ゲームのidle reset、同要求のBrain適用、直後STOPまでの0.4684m移動は記録されているが、試験全体は失敗のまま保存する。最終修正では同じFORWARDを維持して最大2秒、実変位を追加観測する。未commitのswatter猶予プロパティへの直接依存も除去し、試験待機は各120秒と全体300秒の上限内で実警告・被弾を観測する。

`validation/course`の通し試験は`player_text`、実Brain、診断teleport/固定motorなし。約92.98秒、waypoint 2、位置(x=4.91,z=32.99)で`stage_GameOver`となり失敗。32件のBrain適用通知を観測し、controllerError/bodyFaultは空。終端は失敗時の制御抑止によりfresh=false、epoch=8、generation=3、sequence=474。これは通しprobeの入力相関修正後の実失敗であり、完走PASSではない。自動pilotが途中で進めなくなるため、人間の通常プレイでの完走確認と停滞箇所の確認が残る。
