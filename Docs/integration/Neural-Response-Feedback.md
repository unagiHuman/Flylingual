# 神経応答の表示・会話還流

更新: 2026-09-14。仕様書 `Flylingual_Brain_Feedback_Codex_Astra_Spec.md` の実装・検証記録。Windows実Brain→Playerの移動・STOP、観測配送、同一LIF列の非干渉を確認した。Phase Bは12主試行＋再現性対照を実行し、増分の履歴効果を支持せず、未校正のためINCONCLUSIVEで探索終了。**LiveDialogueGroundingはPARTIAL、実マイクとHUD目視は未確認**。`ready=false`／productReady=falseを維持し、身体因果もunknown。

## 最終レビュー修正の検証（2026-09-14）

対象はconfig由来provenance、artifact検証とclassification readinessの分離、Bridge→Unityのduration契約。BrainFrameへのmetadata追加以外の神経数値・刺激・RNG・Action・decoder・身体経路は変更していない。既定threshold／calibrationは未設定、ready=false／productReady=falseを維持する。

Pythonは `.venv-bridge/Scripts/python.exe -m unittest tools.test_neural_response tools.test_neural_classification_ready tools.test_neural_provenance tools.test_neural_calibration_config tools.test_neural_feedback tools.test_native_conversation tools.test_text_conversation tools.test_local_intent_config tools.test_intent_age_config` で **146件PASS（3.927秒）**。configのinput/readout body ID変更、6 Actionの候補、派生metric、unknown producer、null／部分／全threshold、hash／identity不一致、allowedClaimsとの整合、400ms期限を確認。WebSocketの送信待ち後に最新snapshotを取り直す回帰試験はメモリ内transportを使い、実Brain接続試験とは区別する。

Unity 6000.5.9f1は再コンパイルcompleted／failed=false／errors=[]。`Flylingual.Conversation.EditorTests.NeuralReadoutTests` は **16件PASS**。artifact検証のみでは判定可能表示を出さないこと、該当軸のみの判定表示、sourceAge300＋Unity経過50/100/150msに対する400ms境界、欠落のみ750ms互換、fresh=false、不正値、古い身体観測の延命防止を含む。証拠: `artifacts/neural-feedback/final-review-unity-tests.json`。

非干渉は `artifacts/windows-malecns/.venv/Scripts/python.exe tools/neural_noninterference.py --graph artifacts/neuron_checkpoint --config Brain/MaleCNS/config/analog_temporal_v1.json --output artifacts/neural-feedback/final-review-noninterference.json` で **PASS**。実LIF、seed1701、観測OFF/ON各30frame、Python3.10.12／NumPy1.24.3、解析p95=0.6529ms。raw／motor／brain／sequenceと各frameのRNG hashが一致し、前回review-fix記録のrawMotorHashとRNG列にも一致した。rawMotorHashは `3e61747c9aa39bee5c1a8161c1e579665c43292b2da0ec2693e75b7d88cb8075`。OFF/ON wallは3.144/3.036秒、sampled peak RSSは約90.0/91.2MB。source・graph・config hashと測定列は同JSONに保持し、Player経路のidentityとは区別する。

Dev-Local Playerは既存 `HayeringualBuildWindow.Build` 入口で **Succeeded**（08:22:54–08:23:19 UTC）。初めのdelayCall予約は実行されず、古いBuildReportを成功に流用せず直接実行した。直接evalはCLI応答が5秒timeoutとなったがビルドは継続完了し、BuildReportの唯一のerrorもこのCLI応答timeoutだった。C#コンパイル失敗ではない。既存EditorBuildSettingsの1シーン生成差分は今回のコミット対象外。

`tools/neural_player_trial.ps1 -Name final-review-ja -Language ja -Question 0` の日本語1試行は **control_pass**。Player→Bridge→Windows実Brain `127.0.0.1:18766`、MALECNS_EXPERIMENTAL／LIVE、ready=false。約2.9500m前進後にSTOP適用、終了時fresh=true、Playerのresult.errorは空。Playerは147 BrainFrame／145神経観測／144身体相関、記録区間sequence30→154。配送ログは終了直前の追加分と同一sequence配送を含む181神経イベント（sequence30→155、STOP150／FORWARD31）で、最大source age484ms、全件staleAfterMs=750。実configの6readout body IDとgroup、現在Actionの刺激候補、derived／aggregate、artifact未設定と全classificationReady=false、強弱／変化claim抑止が全件一致した。400ms設定は単体で確認し、実Player試行は通常750ms設定である。

Bridge全区間は161一意frame、step p95=181.705ms、analysis p95=0.4367ms、submitted→appliedは6件でp95=316.25ms。Player frame p95=17.0946ms、sampled peak RSS≈570.3MB。単独試行の記述値であり性能受入れや統計的優位を主張しない。運転中のstale／protocol errorは記録されなかった。Player終了時のcontrol close1006と同時に `background_failed: ClientConnectionResetError` が1件残るため、ログ全体errorゼロとはしない。probe内蔵ScreenCaptureも失敗し、目視確認には使用できない。実GPT-Liveへの質問回答は11秒窓で途中のため、会話品質全体はPARTIALのまま。

証拠は `artifacts/neural-feedback/final-review-ja.json`、同`.json.events.jsonl`、`final-review-ja-contract-audit.json`、`final-review-ja-summary.json`、player／bridge／metricsログ。contract auditは実frame identityのsource／graph／config hashと変更ソースのSHAを含む。試行後local.jsonを元のbytesへ復元し、所有Playerは終了した。

Phase Bは再実行していない。既存12主試行＋1再現性対照のINCONCLUSIVE／D_increment≈0を維持し、このmetadata修正を履歴効果の実証に読み替えない。実マイクとHUD目視は今回のgateに含めていない。

## 前回レビュー修正の検証記録（2026-09-14）

以下は最終レビュー修正前の検証記録であり、今回追加するprovenance・classification readiness・freshness contractの再検証を意味しない。

今回の修正はread-only analyzer・表示・会話還流に限定する。`forward`／`turn`別比較・閾値、集計方法と刺激入力readoutの由来、校正artifact検証、人格を維持する短文要約を実装した。**実装済みであることはproduction校正済み・実機受入れ済みを意味しない。** 既定の閾値とcalibrationは未設定で、ready=false／productReady=falseは維持する。

最終統合では、`.venv-bridge/Scripts/python.exe -m unittest tools.test_neural_response tools.test_neural_calibration_config tools.test_neural_feedback tools.test_native_conversation tools.test_text_conversation tools.test_local_intent_config tools.test_intent_age_config -v` が **126件PASS（3.116秒）**。Unity 6000.5.9f1の再コンパイルはcompleted／failed=false／errors=[]、追加の `NeuralReadoutTests` は **4件PASS**。JSONの軸別差・欠測null・metadata・旧consumer互換を確認した。初回の子検証はBrain用venvにaiohttpがなくImportErrorとなったが、Bridge用venvで実行を完了した。

`tools/neural_noninterference.py` を新しい出力先へ実行し、実LIFの観測OFF/ON各30frameでRNG、raw神経出力、motor、sequenceの一致が **PASS**。seed1701、実装済み100Hz確率刺激、Python3.10.12／NumPy1.24.3、解析p95=0.4046ms。`artifacts/neural-feedback/review-fix-noninterference.json` にidentity・source/data/config hashと各runを保存した。これはWindows Player動作の代替ではなく、別の非干渉試験である。

Dev-Local Playerを既存ビルド入口で再ビルドした。CLI eval応答は5秒でtimeoutとなったが処理は継続し、Editor BuildReportでSucceededを確認した。BuildReportのerror1件はこのCLI応答timeoutであり、C#コンパイルエラーではない。既存Editor初期化が以前の1シーンUI設定をEditorBuildSettingsへ反映したが、その生成差分は本レビュー修正のコミット対象外とする。

`tools/neural_player_trial.ps1 -Name review-fix-ja -Language ja -Question 0 -RenderScreenshot` による日本語1試行は **control_pass**。所有Player→Bridge→Windows実Brain `127.0.0.1:18766`、MALECNS_EXPERIMENTAL／LIVE、ready=false。約2.9842m移動後にSTOP適用、終了時fresh=true、Playerのresult.errorは空。probe全体では133一意BrainFrame／131神経観測／125身体相関を記録し、起動完了後の記録区間はsequence28→139。神経イベントは同一sequenceの配送も含め180件で、すべてOBSERVATION_MEASURED／calibration.not_configured、最大age約359ms。180件すべてで集計metadata、DNg100刺激入力とDNa02/DNp09非刺激観測のprovenance、strength/change claim抑止、bodyMovementVerified=falseを確認した。通常設定にproduction校正artifactや推測閾値は追加していない。

今回の実入力は既存probeの合成テキストであり実マイク試験ではない。実GPT-Live回答は「今はSTOPの刺激が適用されたところで、効いたとか拒否したとかはまだ言えない」等だったが、11秒の窓では回答途中。日英persona維持は単体で確認し、実会話品質全体はPARTIALのまま。ScreenCaptureはFailed to capture screen shotでPNGを得られず、HUD目視は未確認。追加のPhase Bや高コスト探索は行っていない。

証拠は `artifacts/neural-feedback/review-fix-unit-tests.log`、`review-fix-unity-tests.json`、`review-fix-noninterference.json`、`review-fix-ja.json`、`review-fix-ja.json.events.jsonl`、`review-fix-ja-contract-audit.json` と同名player/bridgeログ。contract auditは変更ソースのSHAも含む。`review-fix-ja-metrics.json` はPlayer frame p95=16.8693ms、sampled RSS等を記録する。今回の単独試行から遅延性能の統計的優位や履歴因果を主張しない。

後半の「Phase B準備と受入gate」以降は**レビュー修正前の実測・制約の履歴**であり、今回の差分に対する再検証ではない。既存の数値、実行ラベル、HEAD参照、失敗、未確認項目を保持する。Phase Bは12主試行＋1再現性対照のINCONCLUSIVEを変更せず、今回のpresentation/schema変更を理由に再実行していない。

## 実装と境界

`Runtime/Bridge/neural_response.py` の `NeuralResponseAnalyzer` が新規BrainFrameの少数readoutだけを解析する。`server.py` が適用requestとidentityを対応付け、`neural_feedback.py` の単一consumer・最新1件の待機枠を通じて既存ConversationAdapterへ最大380文字の事実を送る。神経readerでGPT応答を待たない。

Unityは `ConversationSessionController` で任意購読し、`NeuralResponsePanel` を `PlayScreenView` の神経パネルへ追加する。`FlyTerrainRuntime` は既存センサー送信位置でThoraxの速度と角速度、既存odometerを読み取る。Brain/LIF/RNG/decoder/CPG/物理/Actionへ書き込まない。

HUDは通常表示を要求、刺激適用、selected VNC raw F/T、motor、backend・mode・ageに絞り、折りたたみの「測定と比較の詳細」にfiltered raw、左右population、身体速度・対応sequence、軸別の前回差と適格性、未校正・刺激系列不固定の説明を表示する。raw、decoder、motor、身体は別の測定層として扱う。raw曲線はmV可変軸、motor曲線は±1固定軸、横軸は**除外した適用frameの終端から0–200脳内ms**。薄い線は前回比較曲線。欠測・stale・相関不成立はunknownでありゼロに補完しない。body対応sequenceが最新神経sequenceより古い場合は、両sequenceと脳内時間差を明示する。

## selected VNC aggregateとreadoutの由来

`forward_raw`／`turn_raw`はMaleCNS全体の活動でも、ニューロン数で加重したpopulation平均でもない。各ニューロンのbaselineからの膜電位差をcell typeごとに平均し、各軸・各側でcell type平均を均等に平均する。軸a（F/T）、側s（L/R）に属するcell type集合をC[a,s]、型cのニューロン集合をN[c,a,s]、各ニューロンのbaseline差をΔV[i]とすると、既存計算は次のとおり。

```text
M[a,s] = (1 / |C[a,s]|) × Σ(c∈C[a,s]) [(1 / |N[c,a,s]|) × Σ(i∈N[c,a,s]) ΔV[i]]
forward_raw = (M[F,R] + M[F,L]) / 2
turn_raw = M[T,R] - M[T,L]
```

単位はmV。cell type数を均等に重み付けする **cell-type equal-weight aggregate** であり、集計そのもの、baseline、刺激、decoderの数値計算は今回変更しない。これはepisode内の200脳内msに対する時間加重平均とは別の集計段階である。

集計を実行する `Brain/MaleCNS/analog_controller.py` 自身が、BrainFrameの `metadata.selectedVncAggregation={version: "v1", method: "cell_type_equal_weight_mean_delta_v", unit: "mV"}` を明示する。Bridgeは受信metadataを検証してイベントへ渡す。backendId／datasetId名だけから集計法を推定する従来方式は廃止し、明示metadataが欠ける旧producerや不正なmetadataはunknownとする。HUD名は「選択VNCの細胞型均等ΔV / Selected VNC class-balanced ΔV」。この追加は既存の集計数値を変更しない。

`metadata.readoutProvenance` の正本は実Brain configの `inputs` と `readouts`。controllerの初期化でgraphに解決済みのindicesを実body IDへ戻し、6 Actionそれぞれのmetadataをsnapshot化する。初期化後にconfig辞書が書き換わっても、既に初期化された刺激・readoutの対応を誤って付け替えない。frameは現在Action用snapshotを使い、LIF状態やRNGを観測metadataのために変更しない。

対象は左右DNa02／DNg100／DNp09の6個、派生DN metricの2個、VNC rawの2個の計10キー。neuron項目は `kind=neuron_readout`、`bodyId`、`configuredStimulusGroups`、`eligibleForDirectStimulation` を持つ。groupは名前ではなくbody IDの一致で導出し、出力は最大16 group・各名64文字に制限する。現在のconfigではDNg100の10045／10056がF groupに含まれるが、同じbackend／dataset名でもinputsまたはreadoutsが変われば結果も変わる。欠損や不正な対応を名前から推定しない。

| Action | 刺激候補group |
|---|---|
| STOP | なし |
| FORWARD | F |
| TURN_R / TURN_L | R / L |
| FORWARD_R / FORWARD_L | F＋R / F＋L |

この対応はcontrollerの実 `ACTIONS` 定義を使用する。`configuredStimulusGroups` は設定された刺激候補集合への所属、`eligibleForDirectStimulation` はその集合と現在Actionのgroupが交わるかを意味する。現在configのDNg100はFORWARDでtrue、TURN_RやSTOPではfalse。**trueでも、その計算窓内にBernoulli刺激イベントが実際に発生したという記録ではない。** falseも、そのニューロンが発火していない、またはネットワーク経由の入力がないという意味ではない。

`DNp09_Hz` と `DNa02Difference_Hz` は `kind=derived_metric` とし、`derivedFrom` にそれぞれ `DNp09_L_Hz/DNp09_R_Hz` と `DNa02_R_Hz/DNa02_L_Hz` を列挙する。直接のニューロンreadoutとして扱わない。`forward_raw/turn_raw` は `kind=selected_vnc_aggregate` とし、対応する `populationDeltaMv.<axis>.R/.L` を `derivedFrom` に持つ。数値の結合方法は上記数式のとおりである。

DNg100が刺激候補に含まれる場合、その値は入力ニューロン自身の活動を含み、独立した下流反応の根拠ではない。GPT-Liveのcompact summaryはDNg100や派生DN metricを判定根拠として使用せず、意思・感情を導かない。Bridge/HUDは由来不明をunknownとして残す。

## 設定

既存Bridge configの最上位 `neuralFeedback` に以下を指定できる。

| キー | 既定値 | 意味 |
|---|---|---|
| enabled | true | 読み取り解析と新capability。有効化しても運動経路を変更しない |
| spontaneousEnabled | true | 適格eventの低優先度実況 |
| cooldownMs | 4000 | 実時間。4000–60000の整数 |
| rawThresholdMv / filteredThresholdMv | {forward: null, turn: null} | 軸別の選択raw／平滑化raw検出閾値、mV |
| motorThreshold | {forward: null, turn: null} | 軸別の無次元motor検出閾値 |
| changeThresholdMv | {forward: null, turn: null} | 軸別の前回差の最低mV閾値 |
| thresholdVersion / calibrationEvidence | null | 校正版／旧根拠参照。自由文字列だけでは校正成立にしない |
| calibration | null | version、artifact、artifactSha256、sourceHash、graphHash、configHashの検証対象 |
| bodyResponseGraceMs | null | 身体応答を待つ実時間ms |
| bodySpeedThresholdMetersPerSecond | null | 前方身体速度の閾値、m/s |
| bodyYawThresholdDegPerSec | null | 身体yaw速度の閾値、degree/s |
| bodyMotorThreshold | null | 身体比較に使うmotor閾値、無次元 |
| bodyYawSign | null | 実機校正したyawとmotor turnの符号対応、±1 |
| bodyThresholdVersion / bodyCalibrationEvidence | null | 身体判定の校正版と根拠参照 |

軸閾値はnullまたは正の有限数値（上限1e6）。同じ4キーのdictでforward／turnを分け、未知軸を拒否する。旧scalarは読込互換として受理できても両軸nullへ扱い、production判定を有効にしない。版・根拠の自由文字列だけでは軸閾値を有効にしない。**既定は未校正なので、応答検出・強弱・残留を推測で実況しない。** 未校正時は有効な測定をOBSERVATION_MEASUREDとして数値表示できるが、strong／weak、RESPONSE_PRESENT、RESPONSE_CHANGEDの意味判定を行わない。数値表示と質問用の事実要約は別に扱う。鮮度は既存control.staleMs（通常750ms）に従い、緩めて合格させない。

`calibration`は起動時にartifactを検証し、frameごとのファイルI/Oは行わない。相対artifactパスの基準はFlylingual repoルートで、JSONは最大64KiB。artifact実在、artifactSha256（SHA-256）の一致、`calibration.version == thresholdVersion == artifact.version`、artifactと設定のsourceHash／graphHash／configHash一致、artifactの`thresholds`と設定の4つの軸別閾値dictの一致を必要とする。各identity hashとartifactSha256は64桁16進。さらに現在受信したBrain identityのsourceHash／graphHash／configHashが校正情報と一致する場合だけ閾値を使う。

artifact JSONは `version`、`sourceHash`、`graphHash`、`configHash` と、4キーそれぞれにforward／turnを持つ `thresholds` を含む。設定だけ閾値を書き換えてもartifactとの一致が崩れるため有効化しない。イベント最上位の `calibration` は `artifactVerified/identityMatched/valid/classificationReady/status/version/artifactSha256` を返す。artifact不在・不一致・未設定はfail-closedとし、同梱できない配布環境もuncalibratedを優先する。今回production calibration artifactは追加しない。既存の身体判定用body*設定は別の校正経路であり、今回の軸別artifact gateによって身体校正済みへ昇格させない。

`artifactVerified` はartifact自体の検証成功、`identityMatched` は現在Brain identityとの一致を示し、互換用 `valid = artifactVerified && identityMatched` とする。**valid=trueは全判定の校正完了を意味しない。** null閾値を含むartifactも検証には成功し得るため、次の `classificationReady` を判定別に使う。

| classificationReady | artifact検証・identity一致に加えて必要な閾値 |
|---|---|
| responseForward | rawThresholdMv.forward |
| responseTurn | rawThresholdMv.turn |
| changeForward | changeThresholdMv.forward |
| changeTurn | changeThresholdMv.turn |
| stopResidual | rawThresholdMv・filteredThresholdMv・motorThresholdのforward／turn計6値 |

readinessと実際の判定は共有関数 `Calibration.threshold(key, axis, identity)` を使う。検証不成立またはnull閾値はNoneとして扱い、当該軸のclaimを成立させない。例えばartifactが検証済みでもchangeThresholdMv.turn=nullならchangeTurn=falseで、turnを理由とするRESPONSE_CHANGEDは出さない。ready=trueでも方向符号、比較適格性、継続時間等の条件を満たさなければclaimは成立しない。

HUDは判定が全て使えない場合「未校正・数値のみ」、一部だけ使える場合「一部校正済み」として扱い、比較のF/Tごとにnumeric onlyか校正閾値超過かを分ける。artifact検証成功だけで未校正表示を消さない。旧 `calibrationEvidence` の自由文字列は判定を有効化するauthorityではない。

解析バッファは脳内10秒かつ512frame以下。適用境界の最初のframeは比較窓から除外し、以後200msを時間加重で集計する。`comparison.timeOrigin=end_of_excluded_application_frame` は、その除外frameの**終端**が比較相対時刻0であることを示す。刺激送信時刻や実時間0ではない。同一Actionの維持更新は新刺激立ち上がりとしない。epoch・会話世代・Brain identity変更で参照を失効させる。

## Action別比較とruntimeの解釈

FORWARDはforward、TURN_R/Lはturn、FORWARD_R/Lはforwardとturnを**別々に**比較し、STOPはresponse-change比較対象外とする。期待符号はforwardが正、右turnが正、左turnが負。`RESPONSE_PRESENT`は対象となる全軸がそれぞれのraw閾値を期待方向で超える必要があり、複合Actionの片軸だけで完全な指示方向応答としない。継続時間等の既存gateも維持する。

`comparison.axes.forward/turn` は各軸の `eligible/reason/currentMeanMv/previousMeanMv/deltaMeanMv/directionalDeltaMv/changed` を返す。符号付きdeltaと期待方向でのdeltaを分け、差を二軸平均で相殺しない。各軸のchangedは比較適格・校正済みchange閾値超過・前回と今回とも期待方向の条件から判定する。`changedAxes` は変化が成立した軸、最上位changedはそのOR。最上位eligibleは必要軸すべての観測比較適格性であり、校正済みの意味ではない。未校正でも比較可能な数値差は表示できるが、changed／RESPONSE_CHANGEDを成立させない。

旧consumer向け `currentMeanMv/previousMeanMv/deltaMeanMv` のforward／turn辞書は維持し、新しい判定の正本はaxesとする。通常比較は、同一Action・適用相関・identity・観測窓等を満たす過去episodeとの観測比較であり、刺激cell/tick系列の固定比較ではない。刺激の確率的変動を除外できず、`comparison.causalStatus=observed_difference_only` を維持する。イベント最上位は比較適格時に同値、比較不能時はunknownで、`cause=stimulus_variability_not_excluded` を伝える。「同条件」やBrain state／historyが差の原因という表現は使わない。

Phase Bだけが刺激cell/tick系列を固定して履歴依存性を分離する診断である。既存12主試行＋1対照ではD_incrementがほぼ0、未校正でINCONCLUSIVEであり、runtimeで観測できる試行間変動を履歴効果の実証へ読み替えない。rawが0でも全脳静止ではなく、STOP後の残留はselected_neural_readout／decoder／both／unresolvedを維持する。

## Control WebSocket追加契約 v1

既存BrainFrame/motorの数値・必須fieldを維持し、BrainFrame metadataへ上記の由来定義を追加する。`bridge_state.capabilities` のstring配列に `neural_response_v1` がある場合だけ、Unityは以下を送る。旧Bridgeや機能無効時は追加送受信を行わない。

```json
{"type":"neural_observation_subscribe","controlEpoch":1,"conversationGeneration":1,"enabled":true}
```

購読者だけが `type=neural_response`、`schemaVersion=1` を受信する。任意HUD trafficは制御queueを詰まらせず、過負荷では破棄する。

| 受信field | 単位・意味 |
|---|---|
| controlEpoch / conversationGeneration / sequence | 現行世代とBrain sequence。過去世代を現在値にしない |
| identity | instanceId/sessionId/backendId/datasetId/sourceHash/graphHash/configHash。欠けたhashはunknown |
| mode / fresh / ageMs / staleAfterMs | LIVE等の受信mode、鮮度、観測ageとBridgeの鮮度上限の実時間ms |
| current.requestedAction / requestedRequestId | 要求。受付と適用待ちを適用成功から区別 |
| current.observedAction / appliedRequestId / stimulusApplied | frame由来の刺激適用相関。身体成功を意味しない |
| current.raw.forward/turn | selected VNC readout、mV。turnは符号付き |
| current.populationDeltaMv.forward/turn.L/R | 左右populationの膜電位変化、mV |
| current.filteredRaw / motor | 前者mV、後者無次元。decoder残留と神経rawを分離 |
| current.brainStartMs/brainEndMs/windowMs | 脳内時間。wall timeとは別の軸 |
| current.readoutHz / stepWallTimeMs | 選択DNのHz／1計算窓の実時間ms |
| comparison / currentCurve / previousCurve | 比較適格性・理由、axesとchangedAxes、最大32点の適用相対曲線 |
| selectedVncAggregation / readoutProvenance | BrainFrameが明示する集計法と実config由来のneuron／派生metric／aggregateの区別 |
| calibration / cause | artifact検証・identity一致・判定別readiness／刺激変動を除外していない旨 |
| body | 相関済み実測速度。brainSequence/currentSequence/brainTimeOffsetMsで遅れを明示 |
| allowedClaims / causalStatus / residualLayer | 許される限定主張。通常比較の原因は未確定 |

鮮度はduration contractで共有する。Bridgeは `control.staleMs` をイベントの `staleAfterMs` として送る。Unityは受信時の `ageMs` にUnity自身の受信後経過時間を加え、`currentAge <= staleAfterMs` と `fresh=true` の両方を必要とする。例えばstaleAfterMs=400、sourceAgeMs=300ならUnity側経過50msではfresh、150msではunknownになる。Bridgeの絶対monotonic timestampをUnity時計と比較しない。

`staleAfterMs` が**欠落する旧producerだけ**750ms fallbackを許可する。fieldが存在するが不正な値の場合にfallbackして寿命を延ばさない。Bridgeの `fresh=false` は年齢にかかわらずunknownで、Unityが再fresh化してはならない。event全体の期限が切れたら身体値も現在値として表示しない。body自身もfresh／correlatedとageの条件を維持し、イベントの受信だけで古いbody観測を新しくしない。

Unity→Bridgeの身体観測は `type=body_response_observation`。必須はcontrolEpoch、conversationGeneration、独自sequence、ageMs、brainSequence、brainSessionId、brainInstanceId。任意測定値は以下。

| field | 単位・由来 |
|---|---|
| horizontalSpeedMetersPerSecond | world水平面のThorax速度の大きさ、m/s |
| forwardSpeedMetersPerSecond | Thorax前方向への水平速度射影、符号付きm/s |
| yawRateDegreesPerSecond | Thorax角速度のworld Y成分、degree/s |
| travelMeters | 既存odometerの水平移動距離、m。テレポート等で無効なら送らない |
| unityMonotonicMs | Unity realtimeSinceStartup由来ms。他processの時計と直接減算しない |

ageMsは送信queue滞在時間を加算する。Bridge受信時の単調時計を別途付ける。前方軸は既存 `FlyTerrainSensor.Forward` と同じThorax前方投影を根拠とする。**yawの正符号とmotor turnの符号対応は実機未校正**で、HUDにも表示する。これらは最新観測との相関であり、身体が神経状態だけで動いたという因果証明ではない。

## 会話と判定の制限

chat_onlyでは現在のBrain／身体観測を会話へ流さない。controlでも抑止、切断、古い世代、発話中、危険scene cue等の条件で低優先度実況を落とす。「実況を減らして」「皮肉なし」の希望は提示側で扱う。人格は事実の言い方だけを変える。神経summaryは「設定中の人格・口調を維持して短く」と指示し、hiroyuki_likeの会話的なです・ます等を上書きしない。明示された「皮肉なし」は維持する。

`MOTOR_BODY_DISCREPANCY` の判定経路は実装済み。ただし7つの身体校正設定が既定nullなので、**通常設定ではuncalibrated／unknownを維持**する。校正済みでも同一requestの相関、新しい身体sampleが2件以上・100ms以上、応答猶予、鮮度等を要求し、snapshot再送で成立させない。不一致は機構の原因を証明しない。速度を受信できたことだけでbodyMovementVerifiedをtrueにしない。rawゼロを全脳静止、motorゼロを身体停止と説明せず、弱い反応を疲労・拒否・気分として認定しない。

新しいLive向け回答policyは機能enabled時だけ適用し、disabledでは従来経路を維持する。型付きテキスト質問の本文をLiveへ渡す経路を補い、`speak_non_action` は事実を `thinking` へ渡した後、`instructions` で最新質問へ短く直接回答するよう指示する。台本継続や移動催促に置き換えない。このchannelの責務に沿った接続は[公式Live delegation資料](https://developers.openai.com/api/docs/guides/live-delegation)を参照した。最終修正後の実回答品質はまだ検証途中で、実装済みと受入完了を分ける。

`compact_summary`はallowedClaimsを主張gateとし、comparison.axes／changedAxesから適格かつchangedの正規軸だけを要約する。比較事実を先に置き、刺激変動・原因不明・身体未確認・人格保持の文を確保して、380文字（Pythonの文字数）へ収める。入らない副次事実と数値は文単位で省略し、文章やJSONの末尾を切断しない。raw／filtered raw／motorの任意数値は別ラベル。ConversationAdapter.appendも末尾の機械切断を廃止し、380文字超または非文字列を安定エラー `conversation_context_too_long_or_invalid` で拒否する。これは神経以外にも共用される境界なので、他callerも完全な内容を上限内で構築する必要がある。

日英の要約作例（実APIの発言ではない）:

- 「前回の比較可能なFORWARD_R観測と選択VNCの前進軸に差があります。刺激の確率的変動を含むため原因は未確定で、身体動作も未確認です。」
- “Selected VNC response differs from a comparable previous FORWARD_R observation on the forward axis. Stimulus variability was not excluded; cause unknown. Body movement remains unverified.”

## Phase B準備と受入gate（レビュー修正前の記録）

`tools/neural_history_diagnostic.py` は本番から独立した準備済みrunner。Phase A成立後だけ実行する。100ms共通baseline、500msの無刺激またはTURN_R履歴、300msの固定FORWARDまたは無刺激、50ms集計。独立Generatorのcell/tick列とSHAを揃え、実LIFを初期から計算して全状態を持ち越す。主12試行＋A+再現性対照1件。D_totalとD_increment、decoder共通初期／持ち越しを分ける。未校正の既定は12主試行でINCONCLUSIVE。事前登録された校正根拠・方向・mean/integral/peak閾値があり主3seedと再現性対照を通過した場合だけ、未使用3seedを追加して主試行最大24とする。方法・seed・source/data・criteriaのhashを固定し、不一致をSTIMULUS_NOT_CONTROLLEDとして保存する。観測非干渉報告は別の受入参照としてmanifestに記録できる。

| gate | 本記録時点 |
|---|---|
| 解析・提示の単体 | Bridge関連の最新167件合格。実機の代替ではない |
| 診断runnerの純粋単体 | 別途8件合格。イベント・差分・基準・12/24試行制限等 |
| Unity compile/HUD描画 | Windows Playerの実描画起動まで確認。PNGが保存されず、HUDの目視確認は未実施 |
| 同一実LIF入力で観測OFF/ON非干渉 | 30frameのraw/motor/RNG一致、初回PASS。解析p95 0.409ms。`artifacts/neural-feedback/noninterference.json` |
| Windows実Brain→Unity | `127.0.0.1:18766`、MALECNS_EXPERIMENTAL/LIVE、ready=false。最終日本語ON:155frame/154神経観測/147身体相関、sequence20→163、2.937m後STOP。OFF:159frame/観測0、sequence19→162、2.868m後STOP。両Player error空 |
| 実GPT-Live日英 | PARTIAL。日英の恐怖質問で感情・拒否を断定しない実回答を確認。日本語stateは11秒で回答途中、古いscene introが残る。一般雑談等と実マイクは未検証 |
| Phase B履歴診断 | 12主試行＋1対照、再現完全一致。D_incrementほぼ0。閾値未校正INCONCLUSIVE、holdoutなし、探索終了 |
| Phase C身体受入 | 通常移動・STOPと観測配送を上記で確認。履歴による身体差の因果は未証明。姿勢・接触・CPG・慣性の交絡は残る |
| latency p50/p95・RSS | 最新ON解析n171、p50 0.1893ms/p95 0.2955ms。step・RSSは下表。操作適用latencyは各n6で確証不可 |

初期Windows証跡は `artifacts/neural-feedback/windows-ja-state.json`、`windows-en-state.json` と同名の `-metrics.json`、`-player.log`、`.json.events.jsonl`。旧4問を連続する試験では20秒のハエたたきが発動し、会話受入れの条件として不適切だったため1回1問へ変更した。旧試験の失敗を合格に書き換えず、最終grounding指示の効果は下記の限定的な日英回答までとして記録する。

## 確定した最終測定

最新の比較原本は `artifacts/neural-feedback/windows-ja-on-final-summary.json` と `windows-ja-off-final-summary.json`。入力は明示した合成テキストで、実GPT-Live/API/Brain/Unityを通す。音声入力の受入れではない。

| 指標 | ON | OFF |
|---|---:|---:|
| 一意BrainFrame数 | 171 | 169 |
| step実時間 p50 / p95 ms | 110.2793 / 135.1676 | 111.7901 / 133.3757 |
| 解析実時間 p50 / p95 ms | 0.1893 / 0.2955（n171） | 解析なし |
| submitted→applied p50 / p95 ms | 218.5 / 234.0（n6） | 211.0 / 230.25（n6） |
| Unity frame p95 ms | 16.7438 | 17.0485 |
| sampledPlayerPeakRssBytes | 565936128 | 565809152 |
| control queue最大深さ | 4 | 2 |
| 事実context追加件数 / 最大文字数 | 1 / 152 | 0 / 0 |

解析はperf_counter系の単調時計で計測。stepはほぼ同程度だが、別のLive試行の時刻・身体条件は同一ではなく、小Nの操作latencyから「遅延増加なし」を統計的に確証しない。RSSは5秒間隔のsampled値で、瞬間peakや全graph常駐量ではない。ownedProcessTreeのPID別値は別母集団なので単純に同じPlayer指標と混ぜない。OFFログには終了時のbackground_failedが1件あり、Playerのerror空だけで全ログ無例外とはしない。

`windows-en-emotion-v2.json` は163frame/162神経観測/162身体相関、2.864m後STOP、Player error空。恐怖質問への実回答には “I’m not measuring fear” が含まれる。一方、日本語stateは11秒の観測窓で回答が終わらず、古いscene introも残った。`windows-en-emotion-final` のstartup_timeoutは別作業のタイトル画面で停止した既知失敗として保持し、probeは修正済み。成功したv2と失敗したfinalを取り違えない。

最終日本語render試行 `windows-ja-emotion-render.json` はcontrol_pass、155frame/154神経観測/151身体相関、2.859884m移動後STOP、error空、ready=false。実回答は「『STOP』刺激は適用済み。それで運動出力がゼロになってるっていう測定があるだけで、怖さや拒否とは結びつかないよ。」だった。先頭に旧sceneの「でわかる。」が残ったため、日英とも感情を断定しない回答が確認できても全体のgrounding受入れはPARTIALを維持する。

同名 `-summary.json` は所有process treeのRSSも記録し、sampledPlayerPeakRssBytes=645386240。実描画ON試行なのでbatch OFFとの直接性能比較はしない。実描画起動はしたがPNGが得られずHUD目視は未確認。追加試行は行わず、実マイク、一般雑談、古いscene発言の混入を残課題とする。

最終Unity再コンパイルはcompleted、failed=false、errors=[]。render試行終了時のbackground_failed1件はPlayer終了後のClientConnectionResetErrorで、神経解析例外はなかった。通常local設定はja/live/hiroyuki_likeへ復元済み。Git統合は親担当の後続作業で、この記録だけでcommit/push済みとはしない。

### Phase Bの陰性・不確定結果

原本 `artifacts/neural-feedback/history-diagnostic/manifest.json`／`results.json`。seed1701/1702/1703、A+/A0/B+/B0、各9000tick（100+500+300脳内ms）、N=166700、E=19670694。同じ刺激cell/tick列を実LIFに入力し、A+再現性対照のraw/motor差は完全0。入力hash対照も通過。

| seed | D_total平均 F / T mV | D_increment平均 F / T mV |
|---|---|---|
| 1701 | 0.001486 / 0.023382 | −2.22e−10 / −3.98e−10 |
| 1702 | 0.001609 / 0.017543 | 1.33e−15 / −6.11e−15 |
| 1703 | 0.002081 / 0.025647 | 1.78e−15 / 5.17e−15 |

D_totalには残留を含む差があるが、新刺激増分への履歴効果を支持する結果ではない。seed1701の正peakもF=2.21e−6/T=3.96e−6mV程度で、平均だけで全時点が厳密ゼロとは言わない。意味差の工学閾値を捏造せずcriteria=null、最終INCONCLUSIVE、holdout未実行で止めた。主試行wall timeは1.542–1.985秒、windowごとの最大sampled RSSは92459008bytes。mmapをwarm-touchしておらず、低RSSを全graph常駐の証拠にしない。Brain、刺激、decoder、物理を変更して差を作っていない。

### 再現情報と実行入口

Windows Unity6000.5.9f1、Python3.10.12、NumPy1.24.3。実行ラベル `8820d3b-plus-neural-feedback` は作業差分込みで、完成commit hashを意味しない。Phase Bの登録SHAは `92e47cf5cbca68f6ab4e6c04bcfe3ff2958cd6a8befb4397dd063dc3fb817a36`。config SHAは全測定で `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。全source/dataのファイル別SHAはmanifestに保存済み。

Live最終summaryのsourceHashは `7551dbf610622af15be53ac8c33846d9be7a687e0455417ed3a7773843939e21`、graphHashは `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`。非干渉runnerの集約hashとは算出対象が異なるため、文字列の違いを同一方式での不一致と扱わない。Phase A受入参照ファイルSHAは `3ffc3a801e902fdf2b2fc342c90eb863a1dbf3760a5f1e6520ba3c19407bad09`。

repoルートからの数値検証入口（実行済みmanifest/resultsを上書きしない）:

```powershell
artifacts/windows-malecns/.venv/Scripts/python.exe -m unittest tools.test_neural_history_diagnostic -v
artifacts/windows-malecns/.venv/Scripts/python.exe tools/neural_noninterference.py --graph artifacts/neuron_checkpoint --config Brain/MaleCNS/config/analog_temporal_v1.json --output <NEW-REPORT.json>
artifacts/windows-malecns/.venv/Scripts/python.exe tools/neural_history_diagnostic.py prepare --graph artifacts/neuron_checkpoint --config Brain/MaleCNS/config/analog_temporal_v1.json --output <NEW-DIRECTORY> --commit-label <EXECUTION-LABEL> --phase-a-evidence artifacts/neural-feedback/noninterference.json
artifacts/windows-malecns/.venv/Scripts/python.exe tools/neural_history_diagnostic.py run --manifest <NEW-DIRECTORY>/manifest.json --phase-a-accepted
```

Windows実機probe入口はPlayerの `-neuralFeedbackProbe <OUTPUT.json>`、英語は `-neuralFeedbackEnglish`、質問選択は `-neuralFeedbackQuestion <0..3>`。これらは明示的な試験専用引数で、通常起動へ自動適用しない。実行時は親所有の単一Bridge→Windows Brain接続を使い、別Brain probeやMockへ置き換えない。今回の陰性結果を理由に追加seed探索を再開しない。

結果が陰性ならNO_MEANINGFUL_EFFECTまたはINCONCLUSIVEを残して終了する。刺激、重み、decoder、物理を変えて効果を作らない。Phase B/Cの未証明を隠さず、Phase Aの実用性と分けて報告する。
