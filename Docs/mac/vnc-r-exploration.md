# DNa02_R関連刺激：VNC探索 checkpoint

## 結論

**合格条件未達、ready=false。** 検証済みLIF、重み、NT policyを変更せず、
既存R上流10細胞100Hz刺激を3 seedで再実行した。DNa02_Rは100/90/80Hzを
再現したが、annotationで定義したVNC20,429細胞は全phase・全seedで0 spikes。
これは「MaleCNSに運動経路がない」証拠ではなく、固定されたモデル・刺激条件・
観測時間・採用集合でVNC発火応答を検出できなかったという陰性結果である。

## 実験

- seeds: 20260921 / 20260922 / 20260923。
- baseline100ms → stimulation100ms → recovery100ms ×2。各trial内はresetなし。
- N166700、retained E25582938、effective E19670694、dt0.1ms。
- VNC定義：採用済みneuron-only IDのうち公式annotation `superclass` が `vnc_` で始まるもの。
- VNCに投射するdescending/ascending等をすべて含む解剖学的全集合ではない。
- somaSide、somaNeuromere、type等は原annotationの値を保存。未知のpremotor分類・脚対応はnull。
- DNa02_R body10360自身は直接刺激せず、既存の上流mappingを使用。

| 集合 | baseline | stimulation | recovery1 | recovery2 |
|---|---|---|---|---|
| DNa02_R（Hz、seed順） | 0/0/0 | 100/90/80 | 10/10/0 | 0/0/0 |
| VNC全体（spikes、seed順） | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 |

## 候補・path・左右差

| 出力 | 結果 |
|---|---|
| Top50 activated | 正のdelta候補0件。空配列 |
| Top50 suppressed | 負のdelta候補0件。空配列。baseline0では抑制を評価できない |
| 再現するmotor/premotor候補 | 0件 |
| 応答候補へのpath | 候補なしにつき空配列 |
| 左右差 | 両側とも0発火。応答のlateralityは実証できない |
| DNa02_L | R候補が得られなかったため未実施 |

有効有向CSRのBFSによる到達数・直接接続数はsummary.jsonの
`structuralDiagnostics`に分離保存。接続の存在を発火や因果媒介の証拠にしない。
候補が存在した場合に限り、runnerは最短path・edge重み・sign/NT・中間annotationを保存する。

## 保存物・再現

Parallelでflybrain-malecns環境の `python Brain/MaleCNS/explore_vnc.py` を実行。
`checkpoints/vnc-r/summary.json`：設定、trial、空ranking、到達性、左右集計、時間/RSS、hash。
`checkpoints/vnc-r/all_vnc_activity.json`：全20,429細胞のannotation、seed別rate/delta/recovery、平均・delta標準偏差。
入力グラフ配列は前checkpointの生成物を使用し、そのhash manifestを記録。
実行時間はロード・simulation・到達性計算を含み、全細胞JSONのシリアライズを含まない。
RSS peakは同プロセスの高水位（macOS bytes）であり、モデルだけのメモリとは扱わない。

## Blocker / 次の判断

固定条件で再現するVNC応答がないため、VNC output→forward/turnへ進めない。
今後は刺激条件・記録窓・減衰scale・膜電位の閾値下応答等を切り分ける設計が必要だが、
このcheckpointではパラメータを変更しない。Unity/TCP/Windows/Decoder/main mergeは未実施。
