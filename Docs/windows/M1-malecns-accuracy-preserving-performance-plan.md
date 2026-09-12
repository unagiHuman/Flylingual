# MaleCNS 精度保持型性能改善検討

作成日: 2026-09-13。これは実装前の検討報告である。
この計画書の作成段階では既存証拠の照合のみを行った。
その後の実装・数値比較・実機試験は[compiled kernel検証記録](./M1-malecns-compiled-kernel-validation.md)を参照。

## 現行条件

正式な作業対象はFlylingualであり、隣接checkoutは参照しない。
現行の `Brain/MaleCNS/shiu_compatible.py` にはscratch bufferとcount_bufferが導入済みである。
ニューロン数はN=166700、CSR保存エントリ数はE=19670694である。
EはCSRに保存されたedge entry数であり、毎tickに全Eを必ず処理するという意味ではない。
readout対象は119である。
dtは0.1 ms、出力windowは50 msである。
controllerは1 windowを500 tickの `sim.step(1)` として進める。
Actionはwindow境界で与えられ、tickを省略してはならない。
float64、現行係数、刺激、decoder、CPG、PhysX、stale閾値は保持する。

## 最新の実測境界

最新の実Brain＋Unityの声操作検証は[Unity-Native-Conversation-Validation.md](./Unity-Native-Conversation-Validation.md)に記録されている。
対象は2026-09-12 23:42 JSTの`validation-20260912-234219`である。
最新evidenceのaggregate source hashは`3755ee05a6d6e9b622f0ec7522fb8d73bbb77303be4217ef67dbdda4182d8fd7`である。
現行8ソースから再計算したaggregate hashも一致した。入力は文字であり、実マイクによる音声操作の検証ではない。
実行環境はPython 3.10.12、NumPy 1.24.3で、Numba、Cython、llvmliteは未導入である。
BrainFrameは10件、step wall timeは最小510.05 ms、平均619.82 ms、最大756.10 msであった。
BrainFrame 3から4の間隔は766 msであった。
UnityはframeAge 747.1 ms、serverAge 768.9 msで停止した。
750 ms制限を超えたため、動作gateは不合格である。
6 Action各3回の指示適用・移動合格数は0である。
この記録は現行の遅延余裕が不足する直接証拠である。

過去のcount-buffer比較は[結果JSON](./M1-malecns-count-buffer-results.json)にある。
3 seed、168窓の直接比較でbaseline平均646.744 ms、candidate平均460.719 msであった。
全168窓で状態配列とBrainFrameの非timing項目が一致した。
これは直接simulationの比較であり、TCPやUnityのE2E測定とは分けて扱う。
別のUnity 136 frame、約79秒のrunはserver step平均580.10 ms、p95 657.62 ms、最大704.74 msであった。
このrunではstale 0/1302、最大frame age 0.702572 sだったが、長時間負荷保証ではない。
過去のproduction-physics記録の平均798.27 ms、p95 912.62 msはcount-buffer前である。
同じ現行baselineの数値として混同しない。
profileの0.635 sもcount-buffer前の計測であり、現在の関数割合には使用しない。

## 改善の目的

目標候補はp95 step <=250 ms、observed max <=500 ms、E2E p95 <=500 msである。
50 ms windowを常時50 ms以内で処理できることはさらに高い目標であり、現時点で保証しない。
将来のmax上限を保証する主張もしない。
速度向上はraw神経出力、decoder状態、BrainFrameの意味を変えずに達成する。
dt拡大、float32化、edge pruning、decoder変更、stale timeout延長は対象外である。

## 提案の優先順

### 1. CPU compiled fused neuron update

第一候補はニューロン状態更新をcompiled fused kernelへ移すことである。
[現行更新](../../Brain/MaleCNS/shiu_compatible.py)は16.67万要素の配列を複数回走査する。50 ms窓だけでニューロン×tickは8335万となるため、中間配列の読み書きと走査回数を減らす余地がある。実メモリ帯域が律速かは未計測である。
初期実装候補はNumba `njit` とし、`fastmath=False`から開始する。
必要な場合だけCythonまたはC++を別候補として比較する。
float64と現行の演算順を保ち、FMAやreassociationを許可しない。
指数係数は現行NumPyで事前計算してkernelへ渡す。
Numbaを使うだけではbit一致は保証されないため、採用条件は実測一致である。[公式の浮動小数点注意事項](https://numba.readthedocs.io/en/stable/reference/fpsemantics.html)もNumPyとの結果差を説明している。
`fastmath`は演算の再結合を許すため使用しない。[公式performance tips](https://numba.readthedocs.io/en/stable/user/performance-tips.html)の高速化倍率を本モデルの予測へ転用しない。

### 2. window loopと観測加算の統合

500 tickのcontroller loopと観測加算をkernel側で完結させる。
small event batchの準備だけは現行NumPyのRNG順を維持して行う。
1 tickごとの観測時点、spike順、count加算順は維持する。
window平均などのframe reductionは最初は現行実装のまま比較する。
Action入力はwindow境界だけで更新し、tick内の入力を新設しない。

### 3. delayed CSR deliveryのcompiled化

delayed CSR deliveryのPython loopを、順序を保存したcompiled loopへ移す。
duplicate targetへの逐次加算順を変えない。
[NumPyの仕様](https://numpy.org/doc/stable/reference/generated/numpy.ufunc.at.html)では`add.at`は重複indexにも加算する。通常の高度indexによる`+=`へ単純置換しない。
active maskはtick開始時の状態を保持する。
発火によるlast更新後にactiveを再計算して、遅延加算の可否を変えない。不応期中のgを勝手に減衰・ゼロ化しない。
last更新、refractory判定、pending orderingを現行の順序で保存する。

### 4. 厳密静止ニューロンの休眠集合

これは高度な後段候補であり、最初のkernel化後に限定する。
`v=-52`かつ`g=0`で、刺激も遅延到着もない集合だけを対象にする。
刺激または遅延到着のtickには必ず復帰させる。
不応期、観測、発火順、閾値判定を省略しない。
閾値近似や近似的な休眠判定は採用しない。

### 5. SIMD・CPU並列

独立したneuron計算だけをSIMDまたはCPU並列化する。
synapse scatterやreductionの順序変更は避ける。
GPU化は別段階とし、今回の精度保持案には含めない。

定数cache、int/bool scratch、割当削減は小規模な補助候補である。
これらは効果が低い可能性があり、主案の代替とは扱わない。

## 数値検証契約

現行実装をreferenceとして固定し、source/data/config hashを保存する。
Python、NumPy、compiler、依存版、seed、dt、window、Action列を記録する。
tick単位で`v`、`g`、`last`、`rfc`を比較する。
tick、pending ordering、spikes、count、RNG状態も比較対象にする。
window境界ではraw出力、decoder state、BrainFrameのtiming以外を一致させる。
欠測、NaN、Inf、parse errorは0へ置換せず、失敗として記録する。

小fixtureではthreshold境界、refractory境界、delay境界を含める。
duplicate target、切替、長いSTOP recovery、record=Trueも含める。
複数seedと6 Actionを使い、同一入力のAB/BA交互順で順序バイアスを確認する。
cold JIT時間とwarm kernel時間は分離する。
現行版を改めて計測し、状態更新、発火判定、遅延伝達、乱数、観測集計、frame構築を分ける。STOPだけでなく全moving Actionで測る。
[controller](../../Brain/MaleCNS/analog_controller.py)の`stepWallTimeMs`は末尾のdeepcopyと、その後のpublish・JSON・socket・Unity受信を含まない。計算時間とは別に要求送信から対応frame受信までのE2Eとframe間隔を記録する。
Actionは窓境界で適用されるため、要求の位相によって現在窓の残り時間と次窓の計算時間が必要になる。計算時間だけを操作応答時間としない。
最初のfull graph比較は3 seed x 7 segments x 8 windows = 168 paired windowsとする。
STOPが未収束ならwindow数を延長し、未収束のまま平均を合格値にしない。
168窓の一致だけで全状態空間、全tick、record=Trueの一般一致とは言わない。
NumbaまたはCython採用後もbit一致を仮定せず、referenceとの差分を再計測する。

## 実動作gate

これはReplayやMOCKの代替試験ではない。
Windows実Brain、同居Bridge、Unity、通常負荷で確認する。
起動設定のendpointとbackendを実行前に照合する。
single controllerを一担当が所有し、並列probeを接続しない。
6 Action各3回、15分継続、frameAge、stale、protocol、E2Eを記録する。
ready値は受信値をそのまま扱い、接続成功だけでtrueにしない。
最終判断はstep性能、神経数値一致、Unity freshness、物理挙動を別gateにする。

## 未実施と判断境界

今回の成果は既存証拠の整理と本計画書だけである。
新しいkernel、Numba、Cython、C++の実装は未実施である。
新規ベンチマーク、Unity試験、TCP試験、15分試験も未実施である。
したがって本書は性能改善の採用承認でも、750 ms以下の達成報告でもない。
次段階では最小のcompiled neuron updateを一つだけ実装し、上記数値契約を先に通す。
数値一致とstep余裕が確認できた後にのみ、CSR deliveryと休眠集合へ進む。

## 参照

- [Codex-Astra-Workflow.md](../Codex-Astra-Workflow.md)
- [Brain-GPTLive-CrossPlatform-Design.md](../Brain-GPTLive-CrossPlatform-Design.md)
- [M1-malecns-count-buffer-validation.md](./M1-malecns-count-buffer-validation.md)
- [M1-malecns-buffer-extended.md](./M1-malecns-buffer-extended.md)
- [Unity-Native-Conversation-Validation.md](./Unity-Native-Conversation-Validation.md)
- [Numba performance tips](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
- [Numba floating point semantics](https://numba.readthedocs.io/en/stable/reference/fpsemantics.html)
- [NumPy ufunc.at](https://numpy.org/doc/stable/reference/generated/numpy.ufunc.at.html)
