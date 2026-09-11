# FORWARD analog readout checkpoint

## 結論

**限定的FORWARD readout検証は通過。採用候補DNg100/BDN2、ready=false。**
固定MaleCNSグラフ上のVNC膜電位から両側共通成分を読み、TURN単独より大きい
forwardを独立3seedで再現した。直進運動や完成backendの検証ではない。

## 候補探索・根拠

MaleCNS annotationのdescending neuron type/instance/synonyms/matchingNotesで
walking、locomot、forward、leg motor、premotorを検索したが直接ヒットなし。
文献機能報告とローカルのtype・side・synonymsを照合し、3組に限定した。
旧FlyWire root ID、旧F刺激mapping、旧校正を流用していない。

| 候補 | MaleCNS L / R body ID | direct VNC targets L / R | 採用判定 |
|---|---|---|---|
| DNp09 | 10783 / 11177 | 257 / 349 | 型単位のFORWARD対TURN分離基準を満たす群なし |
| DNg97 / oDN1 | 13805 / 230783 | 549 / 562 | 2型が候補、平均raw .06942mV |
| DNg100 / BDN2 | 10045 / 10056 | 944 / 942 | 5型が候補、平均raw .17639mV、採用 |

全6DNからeffective graph上で708 motor細胞へ到達可能だが、長いpathの
reachabilityは発火・機能・因果媒介を意味しない。直接edge重み・注釈を全保存。
premotor分類は推測しない。

DNp09の前進関連報告は[Bidaye et al.](https://pubmed.ncbi.nlm.nih.gov/32822613/)、
oDN1/BDN2の歩行促進報告は[Sapkal et al.](https://www.nature.com/articles/s41586-024-07854-7)
を根拠とする。[MaleCNS回路研究](https://www.nature.com/articles/s41586-026-10735-w)
もDNg97/DNg100のwalking関連を記述する。DNp09には文脈依存のhalting報告もあり、
型名だけで本モデルの前進機能を確定しない。

## 実験・population選択

各候補を**両側DNへ直接Poisson voltage input100Hz/cell**で刺激。
これは正規LIFへの入力であり、発火強制・gain増幅ではない。
上流からDNを駆動する回路の追加同定は今回行っていない。
Shiu方式に従い実験入力集合はzero-refractory、その他LIF・本番重み・NT policyは不変。
TURN対照は既存R/L上流mapping。旧TURN population/校正は変更しない。

各3候補＋R/L対照、それぞれseed20261001/02/03で
OFF100 → STIM100 → recovery200ms（100ms×2）。全VNC20,429細胞の
window mean v/g、baseline差、spike、candidate DN firingを保存。

解剖学的候補集合：候補DNからpositive edgeで2hop以内、`vnc_motor`、
脚関連を明記したtype名、両側に同typeが存在。型名フィルターはコードに固定。
未知MN名・premotorを脚関連と推定しない。
機能的選択は校正seedのみで、各側ΔVが全trial正、bilateral mean最小値が
TURN対照最大値の2倍超かつ.001mV超となる**cell type全体**を採用。
個別細胞の符号反転・微調整はしない。
通過した型の等重み平均応答が最大の候補を選択し、独立seedで検証した。
これはデータに基づくpopulation選択であり、選択バイアスを避けた解剖学的発見ではない。

採用5型、R27/L29細胞。既存TURNとの重複14細胞：

- Pleural remotor/abductor MN
- Sternotrochanter MN
- Ta depressor MN
- Tergopleural/Pleural promotor MN
- Ti extensor MN

全IDはselection.json。型内等重み→型間等重み→左右等重み。
`forward_raw=(response_R+response_L)/2`、responseはinitial baselineからのwindow平均ΔV。
`forward=clip((raw-deadzone)/(reference-deadzone),0,1)`。
reference .216684021097mV（校正Fのp95）、deadzone .004333680422mV
（max(reference×.02, 最終STOP raw最大×1.1)）。Action名はdecoderへ渡さない。

## DNg100校正応答

| seed | R ΔV mV | L ΔV mV | bilateral mV | VNC spikes |
|---|---:|---:|---:|---:|
| 20261001 | .115888 | .092765 | .104326 | 0 |
| 20261002 | .282573 | .131584 | .207078 | 0 |
| 20261003 | .228547 | .206955 | .217751 | 0 |

両側増加を再現、完全な対称ではない。DNp09の陰性は本条件・候補集合に限定する。

## Persistent held-out validation

initialize1回、STOP100 → F100 → STOP200 → R100 → STOP200 → L100 → STOP200。
seed20261011/12/13、校正/選択は固定。各10窓、計30窓。

| seed | F時forward | R時forward | L時forward | F時turn |
|---|---:|---:|---:|---:|
| 20261011 | .6128 | .0203 | .0425 | -.1342 |
| 20261012 | 1.0000 | 0 | .0373 | -.1732 |
| 20261013 | .7618 | .0177 | .0400 | +.2656 |

全seedでF>0、TURN時forward rawはF時の半分未満（実測約2～10%）。
既存turnもR正/L負を維持。F刺激時のturn干渉は残り、直進とは呼ばない。
各STOP第2窓ではforward/turnとも0。最初のSTOP窓はforward最大.6027等が残る。
したがって観測した回復上限は200ms窓単位であり、即時安全停止とは異なる。
全raw・g・candidate firing・窓時間は保存結果を参照。

## 保存・再現・計測

Parallel、flybrain-malecns環境で `python Brain/MaleCNS/explore_forward.py`。
必要入力：既存neuron_checkpoint配列、公式annotation、TURN calibration。
実測全90窓（校正60＋検証30）、9.0秒のsimulated time。
runtime75.96秒、RSS579,731,456 bytes、peak771,686,400 bytes。
全体時間は候補connectivity調査と記録を含み、最終JSON serialization前。
これは観測付き実験の性能であり、TCP/E2E/運用性能ではない。

- analog_forward.py：状態だけを入力とするdecoder。
- explore_forward.py：探索・3seed比較・校正・独立検証runner。
- checkpoints/forward/selection.json：候補スコア、選択、校正、検証判定。
- checkpoints/forward/results.json.gz：注釈・edge・全VNC応答・hash・計測。JSONをgzipで可逆圧縮。

runnerはresults.jsonを生成する。共有時は `gzip -n Docs/mac/checkpoints/forward/results.json`
で圧縮（今回32MB→約2MB）。raw数値を削除せず保管した。

## 未実施・制約

6 Action、combined inputs、TCP、Replay、Windows/Unity互換は未実施。
Motor細胞の膜電位は歩行速度や筋出力の生理学的校正ではない。
左右の独立確率入力で振幅・turnが変動する。さらに長い持続刺激、追加seed、
入力順序変更への一般化は未検証。今回の候補選択は3組に限定し総当たりしていない。
DN直接刺激をゲーム入力に採用するか、上流駆動へ置換するかは統合設計で明示が必要。
ready=false、本番weight変更なし、main mergeなし。
