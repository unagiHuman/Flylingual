# Windows Live：受信時刻に揃えた左右前進の比較（2026-09-12）

## 判定

基準のFORWARD_Lは3/3でstaleなし。最初の対応BrainFrame受信から2秒で右へ2.59～3.43度、その後は左へ転じた。実際の左CPG turnが出た後にも最初の0.5秒で右へ0.55～2.12度動くが、その起点から2秒の累積yawは3/3で左。継続的な操舵符号反転とは区別し、初動の遅れ・過渡的な右振れとして記録する。

最小候補として既存0.64秒startup補間をWindows Liveで評価したが、候補側はstaleと神経出力到着時間が変わり、比較条件が揃わなかった。改善扱いせず、既定OFFを維持する。

## 共通条件と新しい観測

Windows実MaleCNS server 127.0.0.1:18766にUnity Playerのみ接続。毎試行、所有するserverを同じseed20270101で起動し、STOP応答を確認。通常のTibia/FootPad接触、初期位相90度、同じ保存物理初期状態、全脚CPG適用後の吸着評価。Brain/decoder、摩擦、joint limit、吸着強度に変更なし。Replay・mockは使用しない。

基準：FORWARD_L/R各3回。候補：同じ6回に-diagnosticJoinSeconds 0.64だけ追加。同一ビルドを使用し、合計12試行。送信後8秒の物理記録と、終了STOP後4秒の待機を行う。

live-wire.jsonlの最初の対応actionの実BrainFrame受信UTCを起点にする。live.csvに物理観測UTCを追加し、body.csvのyawをunwrapして境界時刻で線形補間。motor-use.csvにはCPGが実際に読んだFrame、age、HasFreshFrame、平滑化後motorと位相を物理tickごとに記録する。

「fullyFresh」はその観測区間と開始境界で保持中の指令にstaleがないこと。前の区間で発生したstaleの力学的影響まで排除する定義ではない。行のt、脚ID、固定tickの対応も検査。

## 基準結果

正yaw=右、負yaw=左。表は各3試行の範囲。

|Action|受信後0～2秒のyaw|その区間が完全fresh|期待符号のraw turnが初めて出る時刻|
|---|---:|---:|---:|
|FORWARD_L|+2.59～+3.43度|3/3|1.565～1.634秒|
|FORWARD_R|+12.12～+14.56度|1/3|0.015～0.020秒|

期待符号は分析用に絶対値0.01を超えた最初のサンプルで判定。制御の閾値は変更していない。時刻は受信起点なので、右の約0.02秒はほぼ最初の物理tickのサンプリング幅に相当する。

左は最初の約1秒、CPG turn平均0。受信後1～2秒の平均turnは−0.075～−0.096、2～4秒では約−0.375～−0.377となる。Action名がFORWARD_Lになった時点と、実際に左操舵量が現れる時点は異なる。右は早期から正の操舵量が出るため、左右を等しいmotor入力とは扱わない。

左CPG turnが−0.01を下回った時刻を別の起点にすると：

|試行|起点から0.5秒のyaw|起点から2秒のyaw|
|---|---:|---:|
|L-0|+0.81度|−2.11度|
|L-1|+0.55度|−4.23度|
|L-2|+2.12度|−0.85度|

この一時的な右振れはstaleだけでは説明できない。ただし、小さい左指令が立ち上がる過渡中の姿勢・接触・慣性の寄与を分離したわけではない。Brainの出力開始が遅いことだけで全て説明したとも主張しない。

## 最小候補の試験と不採用理由

既存の有限時間startup補間0.64秒だけを有効化。位相のreset、入力Actionからの補正、接触除外は行わない。

左の受信後0～2秒の右振れは+0.87～+1.79度と小さく見える。しかし候補側の同区間は3/3でstaleを含み、raw左turnの到着は2.015～2.901秒に遅れ、2秒時点では全てまだCPG turn平均0。基準と同じ操舵入力条件になっていないので、改善の証拠に採用できない。

- 基準：stale消費17/2,400tick、受信139 Frame、Brain stepWallTime平均579ms。
- 候補：stale消費149/2,400tick、受信112 Frame、Brain stepWallTime平均728ms。

Frame数と計算時間は開始/終了STOP待機の受信分も含む。計算時間増加を補間のせいだと断定しない。候補を都合よく評価するための再試行やstale閾値緩和は行わない。

## 検証・保存

全12試行でWindows接続、sequence進行、backend=MALECNS_EXPERIMENTAL、ready=falseを確認。client/protocol error 0、各Player終了コード0。処理順によるstance不一致0。全試行でignored-collision-pairs.txtは空。終了はSTOP送信→4秒待機→disconnect→所有server終了。物理的なSTOP完了は別gate。

artifacts/windows-malecns/live-onset/ と live-onset-join/ に各6試行。
各フォルダ：live-wire.jsonl、live.csv、motor-use.csv、body.csv、legs.csv、contacts.csv、support.csv、manifest.json、Player.log、brain-server.log。
集計：各親フォルダonset-summary.json。buildログはartifacts/windows-malecns/live-onset-build.log。

再実行（新しいoutputを指定、専用venvのpython使用）：

```
python tools/run_live_tibia_diagnostic.py --conditions NONE --actions FORWARD_L FORWARD_R --repeats 3 --output <new-output>
python tools/analyze_live_onset.py <new-output>
```

候補は--join-seconds 0.64を追加。既存出力を上書きしない。通常ゲームで補間を有効にはしていない。

## 今回変更ファイル

UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.cs：左右action選択と実消費Frame/UTC記録。
tools/run_live_tibia_diagnostic.py：action選択と補間候補オプション。
tools/analyze_live_onset.py：受信起点の区間分析、鮮度・操舵開始の分類。
本レポート。

SerializeField変更なし。Brain/decoder/本番preset変更なし。未commit、未push。

次の判断は、安定したWindows Brain計算条件で同じLive入力の立ち上がりを比較できるようにしてから行う。今の証拠でcollider削除やsteeringGain増加を本番へ入れない。
