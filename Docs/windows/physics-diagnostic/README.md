# FORWARD_L固定Replay物理診断 — 2026-09-11

**固定入力で右旋回を5/5回再現。主要分類は CONTACT_PHASE_DEPENDENCE。**
同じBrainFrame、初期姿勢、関節位置、ゼロ速度、未接着状態でも、初期CPG位相で旋回方向が変わる。
JOINT_SATURATIONも実測したが、それだけが反転原因だとは確定していない。
全身角運動量から右向きnet angular impulseも確認できた。一方、FootPad別の完全な摩擦impulse分配は未取得であり、法線impulseだけを完全な接触yaw収支と扱わない。

MaleCNS/TCP統合は通過済み（integration_ready=true）。Gameplay/Physics gateは未通過、gameplay_ready=false、ready=false。
Brain、decoder、TCP、本番パラメーター、CPG式は今回変更していない。修正はまだ実施していない。

## 入力・試行・初期状態

正本は前回Unity Liveの生受信ログ：
`artifacts/windows/m1/live/unity-six-20260911-161958/live-wire.jsonl`。
各Actionの最後に受信した実フレームを選び、そのまま `fixtures/*.jsonl` に保存。
保存元と各ファイルのSHA256は `fixtures/manifest.json`。
診断用Replay sourceが同一BrainFrame.motorを保持する。requestedActionを物理へ分岐させない。

| 固定Action | forward | turn |
|---|---:|---:|
| FORWARD | .899111862 | 0 |
| TURN_L | .001136940 | -1 |
| TURN_R | 0 | .692833103 |
| FORWARD_R | 1 | 1 |
| FORWARD_L | 1 | -.735177754 |

FR/Lは異なる実測turn振幅であり、数学的な鏡像入力ではない。位相比較ではFL入力が完全に同一。
フレーム内のtimestamp/sequence等は原本情報として残るが、固定再生の進行には使用しない。

最終検証66試行（各8秒、400 physics steps）：5条件×5回、8位相×3回、90°再現×5回、adhesion4条件×3回。
初期停止を100 physics steps観測し、初期状態を `controlled-initial.json` に一度保存。以降は全バッチで共有。
各trialは新しいscene instanceを読み直し、TeleportRoot、SetJointPositions/Velocities/Forces、root/Rigidbody速度ゼロ、全targetゼロ、adhesion ConfigureRuntimeのResetState、CPG phase指定を実行する。
新規FootContact instanceによりcontact freshnessも空から開始する。既存接触cacheを再利用しない。
保存した位置・回転・関節位置、全joint/root速度ゼロ、attached=0は66/66一致を機械確認した。
位相以外の設定は比較中固定。PhysXの結果そのものには反復間のばらつきがある。

初期Thorax位置=(.01167167,.92108113,.10215746)、回転quaternion=(.05161184,.00446577,-.00338018,.99865150)。
reduced-coordinate配列は浮動rootの6成分を含む24値（脚関節は18）。その全値はresults.jsonに保存。
Unity 6000.5.5f1 Standalone、dt=.02秒。timeScale=5で試験を加速し、時刻はphysics step数で記録。
Live接続なし。初期位相の選択は診断条件であり、ゲーム用CPG式・周波数を修正したものではない。

## 再現と位相依存性

90°、同一初期条件の再現5回：2秒yawは **+58.01 / +55.18 / +55.86 / +45.25 / +51.66°**。
8秒yawも全て右：+187.69 / +138.85 / +266.81 / +151.49 / +70.48°。
Brain variabilityを除いた状態で反転する。これはLive時の軌跡を完全再現したものではなく、同じ固定Brain値による独立再現である。

| 初期位相 | 2秒yaw平均 | 範囲 | 2秒方向（3回） |
|---|---:|---:|---|
| 0° | -46.36° | -49.12〜-41.80 | 左3/3 |
| 45° | +22.20° | +5.87〜+44.83 | 右3/3 |
| 90° | +47.52° | +43.50〜+50.08 | 右3/3 |
| 135° | +26.81° | +22.48〜+34.50 | 右3/3 |
| 180° | +52.09° | +46.83〜+61.30 | 右3/3 |
| 225° | -11.24° | -12.92〜-7.95 | 左3/3 |
| 270° | -57.87° | -64.09〜-51.94 | 左3/3 |
| 315° | -52.03° | -66.19〜-38.11 | 左3/3 |

0.5秒・1秒・2秒・8秒のyaw、変位、fallはresults.jsonに全trial保存。8秒の方向は一部trialで再反転し、長時間軌道はより不安定。

## 5条件比較（初期位相0°、各5回）

| 条件 | command turn | 2秒yaw平均 | 8秒yaw平均 | 2秒全身L_y平均 |
|---|---:|---:|---:|---:|
| TURN_L | -1 | -3.68° | -130.44° | -.4699 |
| FORWARD | 0 | +14.35° | +76.19° | +.3351 |
| FORWARD_L | -.73518 | -49.61° | -252.18° | -.4576 |
| TURN_R | +.69283 | +23.03° | +160.03° | +.3937 |
| FORWARD_R | +1 | +49.40° | +236.07° | +1.8637 |

phase0のFLは左へ動くが、phase90では同じ入力が右へ動く。F単独にも右biasがある。
比較ごとの関節RMSE、接触・adhesion impulse、clampはresults.jsonのbatches/legsに格納。

## Command→最終CPG→関節

本番presetはgain1.5、minimumSideScale=-.5、gait1.6Hz。base Coxa振幅38°、Femur28°、Tibia38°。
gaitDrive=max(abs(forward),abs(turn)*.7)。位相offsetはtripod A=0、B=π、stanceはsin(phase)≤0、理論stance時間.3125秒。

| 固定入力の定常値 | 左scale | 右scale | 左Coxa振幅 | 右Coxa振幅 |
|---|---:|---:|---:|---:|
| FORWARD_L | -.10277 | 1.85（上限） | -3.905° | +70.30° |
| FORWARD_R | 1.85（上限） | -.5 | +70.30° | -19.00° |

FL右scaleのclamp前は2.10277、FR左は2.5。FL/L側steering contributionはbase38°比-41.905°、R側+32.30°。
FRはL側+32.30°、R側-57°。Femur/Tibia振幅は両側とも28°/38°。同じ絶対turnならSideScale関数は左右入替で対称。
CPG motor.turnの符号反転はない。単なるAction名に基づく補正もない。

Coxa外側targetは±70.3°を要求するがjoint limitは±65°。
FL位相90°再現trial0ではRF/RM/RHが各95/400 ticksでtarget clamp。左側は0。
FR位相0°では左右を入れ替えた同じclampが発生する。

| 脚（FL 90° trial0、8秒） | Coxa target/actual RMSE | Femur RMSE | Tibia RMSE |
|---|---:|---:|---:|
| LF | 3.28° | 5.91° | 8.10° |
| LM | 8.77° | 16.87° | 11.74° |
| LH | 1.48° | 5.62° | 7.75° |
| RF | 25.67° | 6.00° | 7.64° |
| RM | 28.62° | 22.33° | 7.91° |
| RH | 25.58° | 6.40° | 7.67° |

外側Coxaの大きな追従誤差を確認。FRでも外側（左）のCoxa RMSEは約25〜29°であり、FL専用の異常ではない。
drive limit=850、maxJointVelocity=100rad/sは左右共通。coxa実joint velocityとjointForceも保存。
jointForceはdriveが実際に生成したトルクの直接計測ではないため、drive force saturationは確定しない。
全関節の実drive torque・velocity limit到達の完全監査は未完。角度target saturationは確定。

## 接触・adhesion・net yaw

各FootPadのstance/grounded、接触点・法線・relativeVelocity、callback impulse、各関節actual、attached/overload/contactLost/swingDetachを時系列保存。
接触はArticulation ownerごとに一度観測し、FootPadとNON_FOOTを分離。self-contactは外部接触積算から除外。
impulseはreceiver側の法線成分が正になる方向へ統一し、元のraw vectorも保存。yawに合わせて符号を選んだものではない。

FL 90°再現trial0の最初2秒：

| FootPad | callback数 | 法線impulse | 接線impulse（API出力） | adhesion normal impulse | adhesion shear impulse |
|---|---:|---:|---:|---:|---:|
| LF | 0 | 0 | 0 | 0 | 0 |
| LM | 13 | 約.10 | 0 | 約.02 | 約.02 |
| LH | 0 | 0 | 0 | 0 | 0 |
| RF | 17 | 約.67 | 0 | 0 | 0 |
| RM | 11 | 約.20 | 0 | 0 | 0 |
| RH | 24 | 約1.76 | 0 | 0 | 0 |

**NON_FOOTの法線impulseは16.85（232 callbacks）**。FootPad以外のcapsule/Thorax接触が支持荷重の大部分を担う。
脚端だけを測って全身の接触を代表させることはできない。
この平地2秒窓ではAPI出力の接線成分と法線接触のyaw impulseは0だが、実際の水平摩擦が0だとは解釈しない。
Collision.impulseと各ContactPoint.impulse和も併記したが、完全な摩擦分配の取得には至らない。
Unity API参照：[ContactPoint.impulse](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/ContactPoint-impulse.html)、[Collision.impulse](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Collision-impulse.html)。

adhesionのr×Fdtは保存されたforceと接触点から推定。接触callback後の点を使うため適用瞬間との差を含む推定値。
これを接触APIの値に加えても完全なyaw収支にはならない。

別経路として、全19 Articulationの `r×m*v + I_world*omega` を固定world原点周りで合計した。
全速度ゼロの初期L_y=0に対して、90°再現5回の2秒L_yは **+1.116 / +.774 / +1.110 / +.798 / +1.074**。
これにより、左指令後に全身が右向きの正味angular impulseを獲得していることは確認できる。
単位はUnity mass・length・second系。これは全身角運動量差に基づくnet impulse推定であり、
移動するThorax COM周りのFootPad別r×F積算と同一の量ではない。接触・摩擦・damping等を含み、脚別完全帰属は未確定。

## Adhesion ablation（初期位相90°、各3回）

| 条件 | 2秒yaw平均 | 範囲 | 右旋回 |
|---|---:|---:|---:|
| OFF | +60.26° | +57.06〜+65.71 | 3/3 |
| normal-only | +50.20° | +48.35〜+52.63 | 3/3 |
| shear-only | +53.50° | +49.37〜+56.86 | 3/3 |
| normal+shear | +50.58° | +42.90〜+57.62 | 3/3 |

adhesionを切っても反転は消えない。ADHESION_ASYMMETRYを単独主因とはしない。
変更はdiagnostic instance内のみ。本番preset assetは不変。

## Rig左右監査

9組の対応関節でmass、limits、stiffness/damping/forceLimit、maxVelocityが一致。
collider radius/height/direction/size/scale、local COM、鏡映後のlocal position/rotationも一致（浮動小数点許容）。
FootPad radius=.052、local offset z=.96は左右共通。anchor位置も一致し、world joint axisは鏡映＋軸符号の自由度の範囲で一致。
anchor quaternion自体は左右座標系で異なるため、文字列一致を要求していない。
意図しないscalar/形状の左右差は確認しなかった。正のjoint angleの意味を含む全制御設計の妥当性まで保証しない。

## 分類と最小修正候補（未実施）

1. **CONTACT_PHASE_DEPENDENCE：確定。** 同じ固定入力と初期状態でCPG位相だけを変えると右/左が反転。
2. **NET_YAW_IMPULSE_REVERSAL：全身角運動量ベースで確認。** FootPad別完全収支による確認ではない。
3. **JOINT_SATURATION：併発を確定。** Coxa外側targetがlimitを超え、actual追従も悪い。単独原因とは未確定。
4. JOINT_TRACKING_FAILUREは候補。大きな誤差は実測したが、反転の必要十分条件を分離していない。
5. CPG_COMPOSITION_ASYMMETRY、ADHESION_ASYMMETRY、COLLIDER_OR_RIG_ASYMMETRYを単独主因とする証拠はない。

最小修正の第一候補は、Actionに依存しないCoxa振幅の実現可能範囲への制限。
例えばglobal base38°に対し、maxSideScale1.85とlimit65°から安全上限は65/1.85=35.135°。
これだけで反転が直るとは断定せず、同じ66条件を用いた候補比較で確認する。
次候補はactivity再開時の実関節姿勢・接地とCPG位相の連続性を保つ処理。
固定の「左Action専用phase」やrequestedActionによるyaw補正は提案しない。
修正を同時投入せず、一つずつ比較する。Brain/decoder/EMA/weight変更は不要。

## 成果物・再現・限界

`results.json`：全66試行、初期状態照合、0.5/1/2/8秒yaw、関節RMSE、clamp、脚別impulse/adhesion、rig監査。
生CSVは `artifacts/windows/physics-diagnostic/controlled-{baseline,phase,repro,ablation}/`：
`body.csv`, `legs.csv`, `contacts.csv`, `pairs.csv`, `reset.jsonl`, `rig.jsonl`, `Player.log`。
初期実装のcollider JSON例外と、独立snapshotを用いた先行runは別フォルダーに保存し、最終66試行には数えていない。
最終66試行のPlayer例外0。fallフラグは2試行で発生しており、軌道安定性の合格ではない。
各trialは8秒であり長時間安定性を証明しない。

新規実装：`FixedPhysicsDiagnostic.cs`（runtime専用、引数指定時だけ有効）と.meta、
`make_fixed_brain_replays.py`、`analyze_fixed_physics.py`、`summarize_physics_diagnostic.py`、fixturesと本報告。
今回のSerializeField変更なし。既存の物理、CPG式、preset、Brain、decoder、TCPの変更なし。
前段Live統合の未commit差分は残っているが、今回の診断による変更と混同しない。

実行順：専用Playerを既存 `WindowsDemoBuilder.BuildMaleCnsIntegration` でビルドし、
`-physicsDiagnostic -demoAction STOP -diagnosticBatch baseline|phase|repro|ablation`
`-diagnosticInitial <共通JSONパス> -fixedFixtures <fixtures絶対パス> -demoOutput <各出力フォルダー>`。
baselineを最初に実行して共通初期JSONを生成し、以降のバッチで再利用する。
分析は `python tools/analyze_fixed_physics.py <各出力フォルダー>`、最後に
`python tools/summarize_physics_diagnostic.py`。
