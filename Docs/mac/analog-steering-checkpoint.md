# VNC analog steering checkpoint

## 結果

**TURN analog readoutの限定検証を通過。server ready=falseを維持。**
固定モデル上のVNC膜電位から、R刺激で正、L刺激で負の連続値を得た。
これはゲーム向け実験decoderであり、生体の旋回速度の校正や完成Live backendではない。
LIF、NT policy、production weights、integrator、delayは変更していない。

## Population / 左右同定

公式annotationのtype=DNa02、instance=DNa02_R/L、somaSide=R/Lから
body10360と523769を照合。旧FlyWire IDは使っていない。
それぞれのpositive direct targetのうち `vnc_motor` かつ同側somaSideを選択し、
両側に存在するtypeのみ保持した。**21 cell types、R40細胞、L37細胞。**
ID・annotationの全一覧は `checkpoints/analog-steering/calibration.json`。
例：Sternal anterior rotator MN、Ti extensor MN、Ti flexor MN等。
全てを脚専用/steering専用と断定しない（hg等を含む広いmotor集合）。
premotorを推測して分類せず、同typeの左右群を比較する。一対一homolog対応の証明ではない。

選択はannotation/connectivityのみ、R/L応答の符号に合わせた細胞の除去・反転はしない。
型間等重み、型内細胞間等重み。左右で細胞数が違っても型ごとの寄与を均等化する。
既存R subthreshold結果を踏まえ、R/L direct VNCの和集合について新たに
baseline、window mean/max/min v、mean g、delta、type別応答を記録した。
単一の強いinterneuronに依存せず、annotated motor populationを使用した。

## Readout / calibration

各100ms窓で `delta_i = mean(v_i) - initial baseline mean(v_i)`。
response_R/Lは各側のtype-balanced mean(delta)。
`raw = response_R - response_L`。
`turn = sign(raw) * clip((abs(raw)-deadzone)/(reference-deadzone),0,1)`。

reference=0.22792254675mV、deadzone=0.004558450935mV。
referenceは校正6trialのSTIM abs(raw)のp95、deadzoneは
max(最終回復STOP abs(raw)最大値×1.1, reference×.02)。個別細胞のgain/sign変更なし。
入力Action名はdecodeへ渡さず、VNC delta-vだけを使う。
max-v差も診断保存するが、decoderは窓平均（持続利用可能な因果的集計）を使う。

校正：各側OFF100/STIM100/OFF200、seed20260921/22/23。

| 刺激 | seed | response_R mV | response_L mV | raw mV |
|---|---:|---:|---:|---:|
| R | 20260921 | .151194 | .018483 | .132711 |
| R | 20260922 | .170220 | .010537 | .159683 |
| R | 20260923 | .113270 | .014829 | .098441 |
| L | 20260921 | .040071 | .286766 | -.246695 |
| L | 20260922 | .045094 | .216700 | -.171606 |
| L | 20260923 | .026585 | .183280 | -.156694 |

全seedで同側優位。ただし振幅の厳密なmirror symmetryではない。
type別左右応答・population gはresults.jsonに全保存。

## 独立seedのpersistent検証

校正を固定し、seed20260931/32/33を使用（seedは整数識別子、日付ではない）。
各trialはinitialize1回、STOP100 → R100 → STOP200 → L100 → STOP200。
各STOP200は100ms窓2つを別記録。膜電位・queue・baselineをリセットしない。
R/Lの上流入力集合は共にShiu方式のzero-refractory入力先としてinitialize時に固定。

| seed | TURN_R | TURN_L | 回復2窓目STOP |
|---|---:|---:|---:|
| 20260931 | +.7470 | -.7977 | 0 |
| 20260932 | +.5210 | -.6454 | 0 |
| 20260933 | +.5672 | -1.0000 | 0 |

R時DNa02_Rは100/90/80Hz、L時DNa02_Lは80/80/100Hz、反対側は0Hz。
STOP最初の100msは正規化出力最大abs .4968が残るため、即時停止とは扱わない。
次の100ms窓ではraw絶対値最大.000973mV、deadzone内となり全trialでturn=0。
これは有限窓の回復確認で、任意に長い入力・任意seedの保証ではない。

## 実行・成果物

Parallelでflybrain-malecns環境の `python Brain/MaleCNS/validate_analog_steering.py`。
既存 `artifacts/neuron_checkpoint`、dataset annotation、上流mappingが必要。
analog_steering.py：VNC状態のみ受け取るdecoder。validate_analog_steering.py：実験runner。
calibration.json：選択集合・校正式。results.json：校正6trial、検証3trial、hash、時間/RSS。
計45個の100ms窓。全体36.21秒、peak RSS460,914,688 bytes。
runtimeはload/全実験を含むが最終JSON serialization前の値。実運用速度/E2Eではない。
各windowWallMsには0.1msごとの観測集計コストも含む。

debug metadataはmotor_readout=VNC_SUBTHRESHOLD_POPULATION、
model=MaleCNS + Shiu-compatible LIF、ready=false、forwardAvailable=false。
BrainFrame wireやTCP serverにはまだ接続していない。

## 制約と次段階

FORWARD探索・校正、TCP、Replay、Windows互換、Unity旋回実測は未実施。
上流刺激からの全経路を含む応答であり、選択populationへの効果がDNa02のみを
因果媒介とするとはまだ証明していない。motor spike生成も今回の合格条件ではない。
全21typeそれぞれがturn機能を持つとの主張もしない。
global background、production gain、threshold変更、main mergeは行わない。

研究背景：DNa02左右発火差と旋回の関係は[eLife原論文](https://elifesciences.org/articles/102230)
にあるが、このモデルのVNC平均膜電位decoderやその数値校正を検証するものではない。
[MANC回路研究](https://elifesciences.org/articles/96084)も背景資料であり、
今回のMaleCNS annotationを置き換えるものではない。
