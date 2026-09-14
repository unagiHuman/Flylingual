# 環境接触・危険イベントの会話還流

更新: 2026-09-14。今回のゲーム目的は **危険を避けてゴールへ到達すること / Avoid danger and reach the goal**。果汁は通過時に接触を観測する環境要素であり、収集目標・スコア・追加操作ではない。既存のゴール物体・判定、Action→Brain→motor→身体の経路を維持する。

## 実装済みの範囲

`BlindSugarRunEnvironmentFeedback`は既存環境の`PlanningArea`と`WideConnectionPad1`だけに果汁帯を配置する。sourceIdはそれぞれ`planning_juice`と`connection_juice`。既存meshを薄い視覚表現として再利用し、新しい物理colliderや移動補助は追加しない。適合する水平な既存足場が見つからなければ作らない。

`SugarTraceZone`は帯の中央70%幅・奥行き1.7の範囲について、足の接地、freshな地形sensor、queryOverflowなし、bodyUnsafeなし、groundPresent、対象足場の一致、身体と接地位置の高さを確認する。空中通過や上から見えただけでは接触にしない。Playing、時間停止なし、fresh Brain、BodyControlActiveの条件でsampleする。各帯はrun中に一度だけ消費され、再接触で増やさない。Bridgeもsourceごとに重複を抑止する。再試行は新しいrun/attemptとして登録する。

タイトル、初回説明、blind UI、導入ナレーションは日英とも危険回避とゴール到達を案内する。砂糖の検知だけをゴール到達と呼ばず、未測定の感情も作らない。

## 危険イベント

| kind | sourceId | 意味 |
|---|---|---|
| run_started | stage | run/attemptの登録。会話の事実は生成しない |
| sugar_contact | planning_juice / connection_juice | 通過中の果汁接触。各source一度 |
| threat_started | idle_swatter | ハエたたき警告の開始 |
| threat_ended | idle_swatter | 実際の移動による警告範囲離脱 |
| threat_cancelled | idle_swatter | 停止・観測中断等による警告取消。回避成功とはしない |
| fall | fall | 有効な条件で確認した落下 |
| swatted | idle_swatter | ハエたたきの命中 |

終了・取消は対応する警告開始後だけ受け付ける。fall/swatted後はterminalとなり、そのrunの追加接触・警告を採用しない。接続状態を確認できない終了を落下原因や回避成功に置換しない。既存の危険ナレーションと新しい環境観測は独立しており、同じ事実を重複して発話させない。

## Unity→Bridge契約

capabilityは`environment_feedback_v1`。`type=environment_event`は次のfieldだけを持つ。未知field、kind/sourceのallowlist外、不正な数値・古いscopeを拒否する。

| field | 制約・由来 |
|---|---|
| kind / sourceId | 上表の組合せのみ |
| runId | 英数字・underscore・hyphen、1–64文字 |
| attempt | 正のint、上限2^31−1 |
| sequence | 正の単調増加int、上限2^63−1。同じsequenceを再採用しない |
| ageMs | イベント観測からの経過duration。有限・非負、Bridgeのcontrol.staleMs以下 |
| controlEpoch / conversationGeneration | 現在の操作・会話世代に一致。boolはintとして受理しない |
| brainSequence | 現在のBrain sequence以下、遅れ16以内の非負int |
| brainSessionId / brainInstanceId | 現在接続したBrain identityと一致 |

先にrun_startedを登録する。異なるrunへ移るときはattemptの進行を要求する。Bridgeは会話generationとBrain session/instanceのscopeが変われば登録をresetする。`clear_current`は最新事実・警告状態を消すが同一runの消費済みsourceを保持し、`reset`は登録・消費状態も消す。Unityもepoch/generation変更時はpendingを破棄して再登録する。

Unityのpendingは最大8件。登録再試行は0.25秒間隔、古いpendingは750msで破棄する。送信にはcontrol会話、接続、fresh Brain、capability、transport queue深さ4未満を要求し、queue滞在時間をageMsへ加える。Bridgeはより短いcontrol.staleMs設定もその値で拒否する。

Bridgeはfreshな接続を要求し、受理しても制御queueが96件以上または満杯なら非必須の観測配送を落とす。神経刺激やmotorを呼ばず、制御メッセージを押し出さない。GPT送信workerは一つで、送信直前にepoch/generation、control会話状態、抑止、切替・解放不明、接続、Brain鮮度・identity、最新sequence、TTLを再確認する。古い事実を遅れて復活させない。

## Bridge→UI／GPTの意味

`type=environment_observation`は`evidenceSource=unity_environment`と`ageMs/staleAfterMs/fresh`を持つ。時計の絶対値をprocess間で比較せず、環境事実の鮮度をdurationで扱う。観測には次の未設定状態を明示する。

```json
{
  "neuralInputApplied": false,
  "affectiveProxy": {
    "status": "not_configured",
    "rewardAssociated": null,
    "aversiveAssociated": null,
    "subjectiveEmotionKnown": false
  }
}
```

GPTへ渡すのは果汁接触・警告・落下等のUnity環境事実だけ。sugar_contactだけは`commentary`で短く知らせ、それ以外は既存の危険発話と競合しないよう`thinking`へ渡す。日英の固定説明は、報酬・嫌悪の神経入力とreadoutが未定義で、神経反応・感情・学習を確認していないことを添える。人格設定は言い方にのみ使い、神経反応を創作させない。UIはControlEventReceived経由で観測を受け取れるが、既存会話captionへ環境イベントを会話本文として挿入しない。

## 未実装の神経入力と次のgate

**果汁接触や危険をBrainの報酬・嫌悪刺激へ変換する処理は未実装。入力定義は提示されていない。** 現行`Brain/MaleCNS/config/nt_policy_exploratory_lif_v1.json`ではdopamineはmodulatoryとしてfast synapseからexcludedであり、環境接触を受けてdopamine報酬学習が成立したとは言えない。接触の記録、危険回避、GPTの発言をreinforcement・快／不快・学習の実証へ読み替えない。

神経入力を追加する前に、MaleCNS実注釈と一次研究から対象body IDと刺激条件（Actionとの関係、強度・時間・対象条件）、readoutの科学的根拠、校正基準を確定する。ユーザーに未知のIDの提示を必須とはしない。その後、観測だけの変更として数値非干渉を要求するのか、新刺激が既存神経経路から自然にmotorへ影響する設計なのかを区別する。目的の挙動へ合わせた固定motor、架空の感情値、推測の報酬ニューロンを導入しない。既存LIF・刺激・decoderを無断で変えない。2026-09-14の候補照合と実装判断は[神経入力候補監査](Affective-Candidate-Audit.md)を参照する。

## 検証と未確認

親担当からの統合結果: Python関連 **165件PASS（3.911秒）**、Unity接触判定 **7件PASS**。`tools/test_environment_feedback.py`は登録・2source消費・危険遷移・重複・期限・scope・identity・queue過負荷・送信直前抑止・motor未呼出を検証する。これらは純粋な契約・接触判定試験で、実Brain・実API・Unity主要プレイ経路の受入れを代替しない。

Windows実Brain試験は `tools/neural_player_trial.ps1 -Name environment-ja -Language ja -Question 0 -EnvironmentFeedback` で **environment_pass**。既存のタイトル開始手順とSTOP適用後、診断の初期条件としてarticulation rootをPlanningAreaの果汁帯手前 `(0, 現在height, 18.5)` へ一度移した。その後は通常のテキスト指示→実GPT-Live／Windows Brain→motor→身体で前進し、接触イベントや固定motorを注入していない。全ステージ走破試験ではない。

`127.0.0.1:18766`、MALECNS_EXPERIMENTAL／LIVE、ready=false。果汁接触1件（planning_juice、Brain seq71）、警告開始1件（seq204）、実移動による解除1件（seq211）を配送ログで確認した。3件ともneuralInputApplied=false、affectiveProxy未定義。Playerは325 BrainFrame／322神経観測、sequence26→328、最初の前進は約2.784m、最終fresh=true／STOP適用／result.error空。Unity frame p95=16.90ms、5秒間隔process samplingのPlayer peak RSS≈594.9MB。実会話は日本語の合成テキスト入力であり、実マイク試験ではない。

神経identityはsourceHash=`061699eac5d36bc8a49b12ff18365fb0827e85cf98f848e5c8f69657c11ed43d`、graphHash=`dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`、configHash=`4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。前回神経readout修正時と一致し、今回Brain数値ソースとconfigは変更していない。Bridgeログはrotationにより冒頭の一部が残らないため、summaryの226frame等を全試行母数とは扱わない。identityと3環境イベントはPlayer受信イベント原本から確認した。

証拠は `artifacts/neural-feedback/environment-ja.json`、同`.json.events.jsonl`、`environment-ja-metrics.json`、`environment-ja-summary.json`、player/bridgeログ、`environment-unity-tests.json`。終了時に旧epochのlocal_safety_observationを破棄するログがあり、異なる世代の操作を再採用していない。内蔵ScreenCaptureは失敗し、HUDの目視・果汁帯の見た目の受入れは未実施。第2果汁帯の実機通過・実落下・実命中・リトライ後の再接触は今回のlive試験に含めず、契約と接触状態の単体試験で検証した範囲と区別する。

live後の送信待ち対策として、environment_observationもWebSocket送信直前に最新snapshotへ差し替えてageを更新し、失効・clear済み観測を再fresh化しないようにした。この追加は `tools.test_environment_feedback tools.test_native_conversation` の **21件PASS（0.849秒）** で検証し、Player試験の再実行はしていない。UnityビルドはSucceeded（09:20:54–09:21:19 UTC）。CLI evalの5秒応答timeoutはビルド処理継続後の完了確認と区別する。

神経報酬入力・感情・reinforcement・学習は未実装または未実証。Phase Bは再実行せず、既存INCONCLUSIVEを維持する。今回の環境イベント追加を理由に履歴効果が成立したとはしない。
