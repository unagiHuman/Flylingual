# 6 Action / 2D decoder integration gate

## 判定

**6 Action acceptance未達、ready=false、sixActionValidationPassed=false。**
FORWARD_Rのturnが独立3seed中2seedで0となる。TCP差し替え・新Replay・
Windows handoff/E2Eは、6 Action通過後というゲートに従い実施していない。
過去の旧MaleCNS TCP結果やfixtureを今回の成功証拠に流用しない。

## 実装範囲

- analog_controller.py：initialize/set_action/step/get_frameを備える実験用persistent controller。
- analog_motor_decoder.py：Actionを受け取らないglobal2軸decoder。
- validate_six_actions.py：純条件5seed＋独立6 Action3seed。
- calibrate_unmixing.py：純校正データのみから2×2 fit、別seedで検証。
- benchmark_analog.py：25/50/100msの観測込み計算コスト。
- config/analog_backend_v1.json：既存population、6 Action入力、暫定未合格校正。
- checkpoints/six-action/：初回・2回目・最終検証のrawをすべて保存。

既存shiu_compatible.py、production重み、NT policy、既存TURN/FORWARD
populationおよび各校正は不変。新configは**本番使用不可の候補**。

入力F=DNg100 L/R（10045/10056）、R/L=既存DNa02-driving上流集合。
combinedは入力集合のunionを実ネットワークへ同時投入。単独frameの加算ではない。
入力は各cell100Hz、dt=.1ms、Shiu方式のstimulus target refractory=0。
initialize時に100ms無刺激baselineを取り、以後状態/queue/baselineをresetしない。

forward rawは既存5型の両側平均ΔV、turn rawは既存21型のR-L ΔV。
raw、selected body ID、各cellのwindow mean ΔV/g、実測DN firingを全frameへ保存。
wire形状は現行BrainProtocol.csのbrainTimeMs、motor、brain、performanceを採用。
DNp09欄は実際のDNp09、DNg100は別debug欄。旧live serverへの接続は未実施。
debug metadataはMALECNS_EXPERIMENTAL / MaleCNS + Shiu-compatible LIF /
VNC_ANALOG_POPULATION / ready=false。Unity JsonUtility実読込は未検証。

## 5-seed純FORWARD contamination

校正seed20261101～20261105。各trialはSTOP100/F100/STOP200/R100/STOP200/L100/STOP200。
各window100ms。FORWARD時turn_raw（mV）：

| 統計 | 値 |
|---|---:|
| mean | .03308098 |
| median | .05613848 |
| sample std | .07220081 |
| absolute p95 | .10720757 |
| 正 / 負 | 3 / 2 |

mixed-sign variability。5seedではsystematic bias不存在までは断定しない。

## Global calibrationの3段階

1. scale/deadzoneのみ。F混入p95×1.1をturn deadzoneに設定。
   独立seed20261111/12/13は0/3合格。弱いTURN_RやFORWARD_Lを消した。
2. 同じ純校正データから2×2最小二乗。F→(1,0)、R→(0,1)、L→(0,-1)、
   初期/回復済STOP→(0,0)。残留第1STOPはゼロ教師にしない。
   混入をゼロ化する同じdeadzone基準。新seed20261121/22/23は1/3合格。
3. 純Fの許容を当初の判定値abs(turn)≤.15として、校正p95から最小deadzoneを
   解析的に求める。新seed20261131/32/33は1/3合格。

combinedとholdout値はmatrix fitに使わない。失敗を除外せず全保存。
最終候補：baseline=(0,0)、global matrix（入力raw mV→中間2軸）：

| 出力軸 | forward_raw係数 | turn_raw係数 |
|---|---:|---:|
| forward | 4.6668799401 | -.0932612257 |
| turn | -1.1917264176 | 6.0258024078 |

reference=(1.1896102702,1.2352704132)、deadzone=(.0934169229,.3378983989)。
forwardはclip((z_f-d_f)/(r_f-d_f),0,1)、turnは符号付き同式。
個別Action/細胞専用の補正なし。適用済≠検証合格。

## 最終3seed結果

| Action | forward raw mV範囲 | turn raw mV範囲 | forward範囲 | turn範囲 |
|---|---|---|---|---|
| STOP回復第2窓 | raw保存参照 | raw保存参照 | 0 | 0 |
| FORWARD | .13360～.25273 | -.02574～.06551 | .478～.993 | -.100～0 |
| TURN_R | .00378～.00733 | .08709～.13543 | 0 | .203～.524 |
| TURN_L | .01055～.01770 | -.21735～-.15764 | 0～.009 | -1～-.698 |
| FORWARD_R | .15702～.18341 | .01494～.24442 | .577～.694 | 0～1 |
| FORWARD_L | .09096～.22012 | -.18503～-.12652 | .318～.864 | -.987～-.610 |

全trial16窓：STOP100→F100→STOP200→R100→STOP200→L100→STOP200→FR100→STOP200→FL100→STOP200。
2回目STOPでは両出力0、回復目標は通過。最初のSTOPは残留を許容し、ゼロ達成扱いにしない。

**失敗の具体例**：seed20261133 FORWARD_Rのraw=(.1834145,.0149384)。
DNa02_R=80Hzでも、matrix後turn=-.128564となりdeadzone内で0。
単にdeadzoneを下げればよいわけではなく、補正後は逆符号にもなっている。
seed20261131ではmatrix後turn=.261056がdeadzone .337898未満。
FORWARDのばらつきと弱いcombined steeringを現在の2つのrawとglobal線形補正で
十分分離できたとはいえない。任意の2×2行列で不可能という証明まではしていない。

## 性能（独立ローカル計測）

| window | warm平均ms | p95 ms |
|---|---:|---:|
| 25ms | 196.17 | 199.72 |
| 50ms | 391.51 | 396.04 |
| 100ms | 787.25 | 805.77 |

各12frame中、先頭除外の11sample。初期化/first step/min/maxもJSON保存。
peak RSS97,026,048 bytes（benchmark process、mmapをwarm-touchしていない）。
小さいRSSを全graph常駐サイズと解釈しない。最終独立検証process peak107,872,256 bytes。
100ms窓の計算は既存Unity stale0.75sを超え得る。TCPでのstale/E2Eは未測定。
25/50msはコストのみ、Action意味や校正の受入検証ではない。

## 再現

Parallel、flybrain-malecns環境で順番に：

1. `python Brain/MaleCNS/validate_six_actions.py`
2. `python Brain/MaleCNS/calibrate_unmixing.py`
3. `python Brain/MaleCNS/calibrate_unmixing.py --allow-small-contamination`
4. `python Brain/MaleCNS/benchmark_analog.py`

configは各段階の候補に更新されるが、sixActionValidationPassedを結果通り保存する。
追加したmetadata/固定100Hz入力チェックはSTOP/API smokeで確認。
旧simulator・旧校正にdiffなし、git diff --check通過。

## 未完了と次の判断

Brain Server結果：未実施。新Replay path：未生成。E2E30sample：未実施。
Windows handoff：未作成。現状を合格Live backendとして引き渡さない。
追加データによる再校正、時間集約/平滑化、readout情報の追加等の設計判断が必要。
今回許可されたglobal2軸補正を超えて勝手に変更しない。
LIF/weight/入力条件/Unity/mainは変更していない。
