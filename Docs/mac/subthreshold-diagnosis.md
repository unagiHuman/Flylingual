# DNa02_R→VNC subthreshold診断

## 判定

**SUBTHRESHOLD_SINGLE_DN：合格条件Aを満たす。ready=falseは維持。**
全371 direct VNC targetへg/v変化が伝播するが、固定gainでは発火しない。
これは採用LIF・刺激条件の結果であり、生体の必要入力や生理学的妥当性の証明ではない。
全ての実装バグを否定するのではなく、今回のsource/index/sign/delay/伝達について確認した。

## 固定条件と診断モード

N166700、retained E25582938、effective E19670694。元のLIF、NT policy、
重みファイルは不変。baseline100ms、stim100ms、recovery200ms。
上流刺激は従来と同じ10細胞100Hz、seed20260921/22/23。
371 targetはeffective DNa02_R rowに属し、annotation superclassがvnc_*の集合。
内部index、annotation、target別重み、signをJSONに保存。

直接対照はDNa02_Rのvへ診断専用pulseを与え、1000,1100,...1900tickの
exact10 spikesを実測確認。ニューロンのthreshold/reset/refractory/delayは変更しない。
通常controllerには統合しない。Co-DNも同じ同期pulse、各10spikesを確認する。
gain2/4/8はメモリ内copyのDNa02_R outgoing rowのみ増幅する感度分析。
新gainの本番採用や全graph増幅は行わない。

## Propagation sanity

全3 seedともg変化371、v変化371、depolarized371、hyperpolarized0。

| seed | 閾値1mV以内 | 3mV以内 | 5mV以内 | 最小margin mV |
|---|---:|---:|---:|---:|
| 20260921 | 0 | 1 | 9 | 2.5724 |
| 20260922 | 0 | 0 | 13 | 3.5070 |
| 20260923 | 0 | 0 | 3 | 3.9547 |

直接100Hz対照：全371 targetが10 presynaptic eventsを受信。
deliveryは発火18tick後（1.8ms）。各deliveryのgは減衰前状態から計算した
`g * exp(-dt/5) + weight`と誤差0で一致した。
構造pre/post/count/signとeffective CSRの371組・変換値も照合した。
上流試行のdelivery残差には他sourceの同時入力が含まれ得るため、直接対照で判定する。

## 最も閾値に近い直接対照target

body801437：IN08A006_R、vnc_intrinsic、somaSide R、somaNeuromere T1。
Motor/premotor・脚対応は未確定。DNa02_R→801437はACh/+、195 synapses、
effective weight5.3625mV（1eventのg加算量であり、膜電位上昇量ではない）。
baseline -52mV、stim max v=-49.23452mV、max g=6.20183mV、margin4.23452mV。
回復終了v=-51.999863mV、g約5.2e-18mV。厳密な電位ゼロではなくbaselineへの漸近。
全target集計、閾値距離Top50、weight Top50、代表target時系列を保存した。

重み分布mV：min .0275 / median .0825 / mean .32822 / p90 .935 /
p95 1.60875 / max5.3625。371本すべてACh/+。

## 診断感度・収束入力

| outgoing gain | 発火したVNC細胞数 |
|---|---:|
| 1× | 0 |
| 2× | 0 |
| 4× | 4 |
| 8× | 16 |

試した離散gainで初発火は4×。正確な臨界gainを測ったという意味ではない。
発火例のv最大値はend-of-tick/reset後の記録なので、閾値通過判定にはspike countを使う。

閾値距離Top50への他descending入力をeffective graphから抽出し、絶対重み順で保存。
最有力target801437への正入力で上位のDN body17211（1.76mV）、12044（1.0725mV）を選択。
負入力もrankingに残すが、興奮性coactivationとは混同しない。

| 条件 | target801437 margin mV | VNC発火 |
|---|---:|---:|
| DNa02_Rのみ | 4.2345 | 0 |
| +17211 | 3.3269 | 0 |
| +17211+12044 | 2.7738 | 0 |

connectome根拠の収束入力で閾値下応答は増強したが、発火には届かなかった。
REQUIRES_CONVERGENT_DRIVEと断定する根拠はまだない。直接/coactivationは
決定論的各1trial、上流実験のみ3seed。同期入力条件の結果である。

## 成果物・制約

`Brain/MaleCNS/diagnose_subthreshold.py`をflybrain-malecns環境で実行。
`Docs/mac/checkpoints/subthreshold/`のupstream3件、direct_gain4件、
coactivation2件、summary.jsonに全集計・入力・hash・時間/RSSを保存。
元graphのhash manifestを参照保存。source hashも保存。
全CNS時系列を保持せず、371 targetを0.1ms刻みで集計する。
代表時系列は1ms刻み＋DNa02 delivery tick。観測のみでintegrator変更なし。

baseline発火0ではrate suppressionを検出できない。今回hyperpolarization0を
生理学的抑制不存在とは解釈しない。gain増幅時にはrecurrentな負応答もあり得る。
残るblocker：変更なしのモデルでVNC発火・motor-related出力が未実証。
production weight変更、background、MotorDecoder、Windows/Unity/TCP、main mergeは未実施。
