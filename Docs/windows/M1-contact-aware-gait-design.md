# 接地を考慮した歩容遷移 — 実装設計 v1

状態：提案。未実装・未検証。FORWARD_L修正済みとは扱わない。
対象：Flylingual / Windows Unity PhysX。Brain/MaleCNSとdecoderの最適化・検証は維持する。

## 1. 決定

既存CPGの目標角生成と、実際に関節へ送る目標角を分離する。その間に、接地状態を見て移行時期と軌道を調整する小さな層を置く。

最初の候補は「支持脚を突然持ち上げず、現在の関節目標からCPG軌道へ連続的につなぐ」。CPGそのものを学習器やIKへ置き換えない。これで旋回が直る保証はないため、診断モードで既存baselineと比較してから採否を決める。

入力はBrainFrame.motor由来のforward/turnだけ。requestedActionはログにのみ使用。身体位置・yaw・速度への直接補正、AddTorqueによる旋回補助、Brain/decoder/重み/EMA変更は禁止範囲のままとする。

## 2. 根拠と未確定事項

確定した観測：
- 同一BrainFrame、同一resetから、初期CPG位相によってFLの身体yaw符号が変わる。
- Coxa振幅を35.135度に制限してclampをなくしても、90度開始の初動は右へ曲がる。
- motor smoothing .35秒は誤旋回を90度から0度条件へ移しただけ。
- 左右の歩幅比を最初から目標turnで決めても90度条件の誤旋回は残る。
- 初回目標角と接地タイミングに位相差があり、NON_FOOT接触も多い。

未確定：関節目標の不連続が逆旋回の単独原因か、どの接触の摩擦が主なyawを作るか。接触の接線方向impulse収支は閉じていない。本設計は未確定の原因を事実として前提にしない。

既存根拠：M1-coxa-bound-comparison.json、M1-gait-onset-results.json、M1-onset-smoothing-results.json、M1-separate-steering-results.json。

## 3. データ経路と所有者

BrainFrame.motor
→ FlyLocomotionControllerの既存motor smoothing / CPG phase
→ FlyLegの純粋なCPG目標計算（NominalLegTarget）
→ GaitTransitionPlanner（新規・診断では既定OFF）
→ LegDriveTarget（角度＋stance意図）
→ FlyJoint.SetTarget / FlyFootAdhesion.SetStance
→ PhysX

重要：SetStanceをCPGとPlannerの両方から書かない。Planner有効時は最終LegDriveTargetだけがstanceを決める。Adhesionの力・detach式・強度は既存のまま。

Phaseを便利な0度へresetしない。global phaseは継続し、各脚がnominalに合流する時期のみ調整する。回転符号に応じた位相の手動選別もしない。

## 4. 現行コードへの対応

- FlyLocomotionController.FixedUpdate：モータ平滑化、位相更新、6脚への適用を所有。
- FlyLeg.ApplyTrajectory：現在は目標計算、SetStance、3関節SetTargetが一体。計算と適用を分割する。
- FlyJoint.Target / Articulation.jointPosition：指令と実角を区別する。実角・速度はradから度へ変換する。
- FlyFootContact.HasFreshSurfaceContact：接地は3tickの保持値。現在接触中の保証ではない。
- FlyFootContact.CaptureFromArticulationOwner：SurfaceRelativeVelocityはowner.linearVelocityであり、接触点同士の厳密な相対速度ではない。この値を滑り判定の真値として使わない。
- FlyBody：Thorax/6脚/姿勢/速度の観測元。
- FixedPhysicsDiagnostic：reset、位相matrix、脚別target/actual/contactの収集を拡張。
- LiveIntegrationTrial：修正済み実時間STOP gateを維持。

## 5. 新規DTO（提案名）

LegObservation:
- fixedTick / collisionTick / contactAgeTicks / observationSource
- actualAnglesDeg[3], actualVelocityDegPerSec[3]
- previousCommandAnglesDeg[3], previousCommandVelocityDegPerSec[3]
- footContact, footPoint, normal, surfaceId, attached
- nonFootContact（別フィールド）、relativePointVelocityAvailable

NominalLegTarget:
- nominalPhase, anglesDeg[3], angularVelocityDegPerSec[3]
- nominalStance, stanceProgress, rawMotor, smoothedMotor

LegDriveTarget:
- anglesDeg[3], commandVelocityDegPerSec[3]
- stanceIntent, stanceProgress, transitionState, reason
- targetLimitHit, trackingError, pendingSinceTick

神経の値、計測値、Plannerの判断を同じフィールドに上書きしない。

## 6. 観測を先に確定する

最初の変更は読み取り専用のsnapshot採取と順序固定。
- collision callbackで観測を保存し、FixedUpdateでは直前の完了済み物理stepのsnapshotを読む。
- freshnessの減算を複数componentから行わない。AdvanceAdhesionTickの現在の所有者と実行順を実装前に確認する。
- 接触点・相手colliderが同定できた場合だけpoint velocityの差を計算。計測不能ならunknown。
- FootPad以外の接触をFootPad支持へ合算しない。
- 非共面・壁接触はflat-ground初版の対象外として明示する。

初版は平地限定。支持点の凸包とCOM投影は補助指標であり、動的安定性や粘着による支持の証明にはしない。支持点が不足/不明なら「安全」と判定しない。

## 7. 脚ごとの状態機械

HOLD → JOIN_PENDING → JOINING → TRACKING
                         ↘ RECOVERING
任意状態 → STOPPING

HOLD:
- 起動時は既存の関節指令を保持し、観測を集める。
- actualをそのままtargetへ代入してジャンプさせない。
- 最初の指令が未定義の場合だけactualを初期targetとし、その事実をログへ残す。

JOIN_PENDING:
- 脳入力の活動が立ち上がった、または目標軌道と現在の指令の差が大きいときに入る。
- 接地している脚のswing開始を無条件には許可しない。
- 6脚の要求を同じtickで集め、Coordinatorが一括決定。for-loop順で結果が変わらないようにする。

JOINING:
- 現在の指令と指令速度から、将来時刻のnominal target/速度へ補間。
- 物理的な接地が失われたら状態を再評価するが、global phaseはresetしない。

TRACKING:
- nominalを追従。通常周期にも支持喪失が起きるので、startupだけを直して完了とはしない。
- 通常歩行へ適用する前に、まずstartup限定版で効果を評価する。

RECOVERING:
- 無接地で支持扱いされた脚など、期待した接触と観測が食い違った状態。
- 未支持の脚を着地探索済みと偽らない。初版では新しい探索運動を追加しない。
- 他脚の新規swingを保留できるが、物理をfreezeしない。

STOPPING:
- raw入力がSTOPだから瞬間的に全脚target=0としない。
- 既存motor出力の減衰に沿って中立目標へ連続的に移る。再始動で古いJOINの計画を再利用しない。
- 神経刺激取消、motorゼロ、身体停止、落下を別判定にする。

## 8. Swing許可の初版ルール

最低限の診断用保守ルールとして、1回の更新で新しくswingへ入る脚を1本までに制限する。他脚の既存swingを強制中断しない。

優先順位：nominal上での要求待ち時間 → 観測の鮮度 → 同点は回転する公平な順序。左を常に優先しない。

許可前の条件：
- 対象脚を除いたfreshな支持候補があり、flat-groundの支持指標が悪化しない。
- 支持とみなす脚が既にswingへ予約されていない。
- target tracking errorが許容範囲。

ここで脚数だけの条件や凸包内判定は「安定保証」ではない。閾値はログを基に決め、未検証値を本番設定へ入れない。

重要な打切り：待機時間に有限上限を設ける。1周期待っても合流できない場合はdiagnostic gate不合格とし、延々停止して逆旋回を隠すことを認めない。fallbackで新規yaw力を与えない。

この逐次swingは元のtripodタイミングを変えるため、純粋な平滑化ではなく明示的な歩容変更である。初版の診断ではこの変更単独の効果を測る。

## 9. 関節軌道の連続化

各関節に三次Hermite曲線を使う候補。開始(q0,v0)は直前の指令と指令速度、終端(q1,v1)はt+Tでのnominal値。q1は固定予測として保存し、毎tick終点を更新して永遠に到達しない構造を避ける。

u=(t-t0)/T、0<=u<=1
q(u)=(2u^3-3u^2+1)q0+(u^3-2u^2+u)T v0+(-2u^3+3u^2)q1+(u^3-u^2)T v1

- C1連続を目標とする。加速度連続までは主張しない。
- 式の端点一致だけでなく、区間内極値・速度・既存joint limitをチェックする。
- 不可能な軌道はT延長または保留。上限Tで不合格を返す。
- 生のnominalが65度上限を超える場合、現在のSetTargetと同じ実効上限を使って比較し、clampと導関数の不連続をログ化。振幅変更はこの実験と混ぜない。
- commandは連続でもactualが追従する保証はない。target/actual差を独立に判定。
- 入力反転・STOPは再計画するが、開始点はその瞬間のcommand/command velocityで連続性を保つ。

## 10. パラメータ管理

最初は診断専用構造体、既定OFF。既存FlyGameplayPreset.assetは変更しない。

決める値：接触安定tick数、tracking error許容値、合流Tの範囲、支持指標の余裕、待機期限、逆yaw許容幅。

初期探索は少数の事前登録候補に限定する。全組合せ探索は禁止。1周期は現行1.6Hzなら約.625秒だが、Tにそのまま採用した実績はない。現行の関節velocity制限値を生理学的な速度として使わない。

## 11. 実装順と最小差分

A. 観測のみ
- 新規GaitObservationSnapshot.cs。
- 既存callbackの更新tick/取得元を追加。
- 物理やtargetは変えず、既存試験ログとの一致を確認。

B. 計算と適用の分割
- FlyLeg.CalculateNominalTargets / ApplyDriveTargets（提案）。
- Planner OFFで従来のtarget列が一致することを確認。SetStanceの呼出順も維持。
- FlyJointへlimitの読み取り専用propertyが必要なら追加。serialized fieldのrenameなし。

C. 軌道の連続化のみ
- 新規GaitTransitionPlanner.cs。支持スケジューリングはまだ無効。
- 数式とjoint limitをテストし、target連続性・actual追従を実測。

D. 接地に基づく許可
- 同じPlannerにCoordinatorを追加。C単独と比較して効果を分離。
- 失敗したDiagnosticSeparateSteeringを有効にしない。

E. 合格した場合だけproduction有効化
- Unity Live、Replay回帰、STOP・落下を確認した後、単一presetとして固定。
- mainへのcommit/pushは別途指示に従う。

## 12. 検証ゲート

G0 純粋計算：端点/導関数/途中極値、有限値、joint limit、STOP再計画、同一tickでの予約競合。
G1 OFF回帰：同一入力で関節target/stance列が従来と一致。PhysXの軌跡は非決定性を考慮し完全bit一致を要求しない。
G2 小規模：FL/FR × 位相0/90 × 3 = 12試行、同じreset。最初に失敗を再現した条件を通す。
G3 位相：G2通過後にFLの8位相×3、FRの鏡像・同位相比較。TURN_L/RとFORWARDも別確認。
G4 遷移：STOP→F→STOP、F→FL→F、FL↔FR、TL↔TR。各変更前後のtarget/actual/contactを保存。
G5 Live：既存0.75秒staleを維持して実行。通過までready=false。

採否：
- 2秒/8秒の最終角だけでなく、全時系列の最大逆方向yawを評価。
- 初期settlingのみの対照から許容幅を事前に定義する（暫定2度などを科学的確定値にしない）。
- 逆旋回が減っても、動かなくなった/待機し続けた/前進距離が大幅低下した候補は不合格。
- 起動位相による成功の入れ替わり、方向反転の非対称、過大なSTOP遅延があれば不採用。
- 閾値・評価窓を結果を見て有利に変更しない。変更時は別試験として記録。

## 13. 必須ログ

per tick: raw/current motor, global/nominal phase, planner state/reason, nominal/command/actual angles, command velocity, tracking error, support snapshot age, swing request/permission, contact/attached, wait age, transition T, limit violation。
body: signed yaw rate, yaw積算、変位、落下、Thorax/非FootPad接触。

contact impulseの取得不能項目はunknown。normal impulseだけから摩擦yawを断定しない。主要比較表は初動、2秒、8秒、最大逆yaw、進行距離、待機時間、STOP復帰を併記する。

## 14. この設計の限界と中止条件

既存rigはNON_FOOTで荷重を受けているため、FootPadだけに基づくPlannerが成立しない可能性がある。G2でfreshな足支持を得られない場合、Plannerで無理に補わず、rest pose/足配置/接触を別タスクとして見直す。この場合は設計仮説不成立であり、脳の失敗とは扱わない。

この設計のゴールは位相に頑健な歩容遷移。生体の反射・筋肉を再現したという主張ではない。成立しない場合は候補をOFFへ戻し、観測・失敗記録を残す。
