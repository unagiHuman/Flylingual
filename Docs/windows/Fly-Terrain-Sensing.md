# ハエの地形センシングと足先補正

このセッションの段差・障害物対応。既存の接地用モデルを対象に、Unity物理空間の局所観測を追加する。既存18関節、6 FootPad、モデルの階層と寸法を維持する。

## 接続と責務

`FlyTerrainRuntime` は groundedTripodGait が有効な FlyBody に、Sceneロード時にセンサーと補正コンポーネントを付ける。既存Sceneを保存し直す必要はない。起動引数 `-disableTerrainSensing` で比較用に無効化できる。

- `FlyTerrainSensor`: 重力方向への地面Raycast、前後左右と斜めの8方向・2高さのSphereCast、足裏中心と四隅の支持面サンプル。自己ColliderとTriggerを除外する。上面の高さ、傾斜、支持幅、前方障害物、左右前方の崖、胴体の異常姿勢を観測する。
- `FlyTerrainTraversal`: 新鮮な実Brain出力による歩行中だけ補正する。遊脚の着地予測を胴体の移動に合わせて更新し、縁の少し先の上面も調べる。遊脚中は再確認した上面高さを保ち、足先の高さを調整する。支持判定は既存FootPadの実接触を使う。Raycastのヒットを接触成立に置き換えない。異なる高さの実接触がある場合は、支持脚の目標だけを補正して胴体の支持姿勢を調整する。
- `FlyTerrainKinematics`: 現在の関節位置・軸から仮想的に足先位置を計算し、既存関節の角度目標だけを制限付きで補正する。driveへの書き込みは既存FlyLegが所有する。
- `FlyLocomotionController`: 危険時または着地待ち中に位相の進行を保留し、通常の目標出力へ足先補正を挿入する。Brainのforward/turn、CPG周波数、摩擦、rootの力やTransformを変更しない。
- `ConversationSessionController`: 既存WebSocketと既存 `local_safety_observation` 契約で観測をBridgeへ送る。control epoch、conversation generation、sequence、観測年齢を付ける。新しいmotorや経路指令は作らない。

接触を支持として使う面には、既存の `FlyGroundMarker` または `FlyStepObstacle` が必要。その他Colliderも障害物として検知するが、足の実接触契約を自動変更しない。

## 初期値と停止条件

距離はモデルの実寸から得る Reach（Femur→Tibia→FootPadの長さ）を基準とする。検証リグでは Reach ≈ 1.220878 Unity unit。

| コンポーネント / SerializeField | 初期値 | 意味 |
|---|---:|---|
| Sensor / terrainMask | 全Layer (`~0`) | 地面・障害物を問い合わせるLayer |
| Sensor / sampleInterval | 0.05秒 | 周囲観測の間隔 |
| Sensor / maximumSlope | 40度 | 歩行候補面の最大傾斜 |
| Sensor / stepHeightFraction | 0.30 | 候補として許可する段差高さ / Reach（通過保証値ではない） |
| Sensor / maximumDropFraction | 0.20 | 最大下り段差 / Reach |
| Traversal / maximumCorrectionDegrees | 35度 | 名目角度からの最大補正 |
| Traversal / correctionSpeedDegrees | 90度/秒 | 補正の変化速度 |
| Traversal / swingClearanceFraction | 0.07 | 遊脚の追加クリアランス / Reach |
| Traversal / contactWaitSeconds | 0.12秒 | 遊脚→支持脚時の接触待ち上限 |
| Traversal / stepClearanceWaitSeconds | 0.25秒 | 上り段差の高さに足先が達するまでの位相待ち上限 |
| Traversal / maximumPostureLiftFraction | 0.12 | 混在する支持面に対する支持脚目標高さの補正上限 / Reach |

観測が0.25秒を超えて古い、問い合わせバッファが飽和、胴下の支持面が不明、胴体が55度を超えて傾く場合は歩容を保留する。前進時には、高すぎる障害物と近い崖でも保留する。空中や当たり判定の内側からのRaycast失敗を、安全な床がある状態として扱わない。判定は新しい観測で再評価する。

高い壁を自動的に乗り越える、未知の経路を自動探索する機能ではない。周囲8方向の距離と旋回候補は観測として提供する。前進を阻止した後の方向変更は、既存の入力→Brain経路で行う。背後の崖、狭い隙間、動く床、連続階段、斜面の限界条件は別途実測が必要。

## 独立した検証Scene

`FlyBrain/Terrain/Create independent terrain scenes` で元のGroundedContactReviewを基に5つのSceneを再生成する。元Scene・共有リグは保存し直さない。

- Flat: 平地。
- Step: 高さ0.18 unit、前縁z=2.4の広い台。
- StepTall: 高さ0.30 unit、前縁z=2.4の広い台。
- Wall: 高さ3 unit、前面z=2.4の壁。
- Edge: z=2.6で床が終わる崖。

`FlyBrain/Terrain/Build Mac terrain Players` は独立した5つのMac Playerを `artifacts/terrain-sensing` に出力する。

## 記録と検証範囲

`-terrainLog -demoOutput <path>` で10Hzの `terrain-*.jsonl` を出力する。通常実行ではファイル記録しない。キーは `observation`（ground/surroundings/edges等）、`feet`（実接触・着地点・補正角・実足位置・目標位置）、`bodyPosition`、`bodyVelocity`、`phase`、`postureLift`、`hold`、`reason`、`brainSequence`、`forward`、`turn`。

今回のMac実測は、ユーザーが許可したMac例外を使用する。Unity→専用Bridge `127.0.0.1:28769`→Mac実MaleCNS `127.0.0.1:28768`。controlは `127.0.0.1:28770`、conversationはoff。既存LiveIntegrationTrialから通常のSTOP/FORWARD/STOP入力を送信し、固定motor・Replay・mockで代替しない。

測定結果は同ディレクトリの `results.json` と各runの `command.json`、`live-wire.jsonl`、`live-motion.csv`、`live-events.txt`、`terrain-*.jsonl`、連続PNGに保存する。接続応答の `ready=false` はそのまま保持する。Windows実機と音声/GPT経由の安全通知往復は今回の実測範囲外。

### 2026-09-13 最終実測

最終コードは `build-07.log` の5 PlayerビルドでC# error 0、build成功。Unity 6000.5.5f1 / macOSで実施した。既存コードの警告は残るが新しいTerrainコードのC#警告はない。リポジトリ指定の6000.5.9f1とpackage lockは元に戻し、Macビルド時の版を `build-environment-final.json` に保存した。Windows Editor/Playerの検証に代えるものではない。

各条件1回、8秒のFORWARD入力の後にSTOP。距離は入力開始時の向きに投影したThoraxの移動量（Unity unit）。段差通過は胴体と全6足が前縁z=2.4を越え、上面で接触・歩行が続くことを確認する。既存runnerの `BASIC_GATE_PASS` は前進・停止の基礎判定であり、単独では段差通過を意味しない。

| 条件 / run | 8秒間の前進量 | 地形についての結果 |
|---|---:|---|
| 平地 / final-Flat | 9.126 | 歩行・停止。postureLiftは全期間0 |
| 高さ0.18 / final-Step | 5.986 | 胴体・全6足が上面へ移り、歩行・停止 |
| 高さ0.30 / tall-06 | 5.624 | 胴体・全6足が上面へ移り、歩行・停止 |
| 高さ3の壁 / final-Wall | 0.400 | 前進中にobstacle_too_highを検出し歩容を保留。最終Thorax z=0.346、壁前面z=2.4 |
| 崖 / final-Edge | 0.973 | edgeを検出して歩容を保留。最終Thorax z=0.879、床端z=2.6。落下なし |
| 高さ0.30・補正なし / tall-baseline | 0.229 | 前縁で足踏み、未通過。STOPは成立 |
| 高さ0.18・補正なし / step-baseline | 9.680 | 通過。低段差では補正なしの方が速い |

高さ0.30の最終試行は、開始約6.75秒後に6足すべてが前縁を越え、足中心高さも0.35以上になった。6脚それぞれの上面での実接触を記録し、アプローチ・乗り上げ・通過後のPNGも目視した。支持姿勢補正の最大指令量は0.1465 unit。これを実際の胴体上昇量と同一視しない。

最終5試行すべてでPHYSICAL_STOP_CONFIRMED。BrainFrameは151〜173件/試行、sequence単調増加、750msを超える接続中フレーム年齢0、protocol error 0、runtime exception 0、query overflow 0。backendはMALECNS_EXPERIMENTAL、mode LIVE、受信readyはfalseのまま。通過した高さ0.30試行のraw forward平均は0.812、補正なしは0.777であり、同一motor列を再生した比較ではない。単発試行で、独立seedによる成功率は測定していない。

入力送信から対応appliedRequestIdのBrainFrame受信までの中央値は、高さ0.30の最終試行で129.6ms（8件）。これは身体の反応時間とは別の値。Brain側の計算時間・source/config/graph hash・instance/session IDは `results.json`、最終ソースのSHA256は `final-source-hashes.json`、入力と遅延は `latency-and-motor.json`、プロセスRSSの単発スナップショットは `brain-processes.json` に記録した。RSSはピーク値ではない。

支持待ちと姿勢補正には段差上で速度を落とすトレードオフがある。低段差の通過時間短縮は未達。高い壁の自動迂回、複数段の階段、狭い踏面、斜面、移動床、背後の崖、Windows、音声/GPT連携の往復は未検証（自動経路探索は未実装）。既存配布アプリの差し替えは行っていない。Unityソースと独立したMac検証Playerを更新した。

途中版の失敗も `build-history.json` と各runに保持している。20秒観測を試みた2件は、観測スクリプトのepoch参照エラーとBridgeのmanual_tcp_has_input_slotによる入力拒否で、前進を測定できなかった。`invalid-runs.json` に分け、通過・停止の試験母数に含めない。Bridgeの入力優先順位は変更していない。

元のPhysicsRig関連スクリプト、FootPad、関節、共有config、元Sceneは変更していない。リグ・元Sceneの保存済みSHA256との一致とGit差分を確認した。コミット・プッシュは未実施。
