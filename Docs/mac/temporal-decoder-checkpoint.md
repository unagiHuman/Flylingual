# Causal temporal decoder checkpoint

## 最終結果

**EMA100ms＋左右対称turn hysteresisで独立5/5 seed通過。**
seed20261231～35。安定期最後200msでF/R/L/FR/FLの各条件を全て維持し、
STOP全25遷移で300ms以内に両出力0。初期STOP5件も0。

| Action | forward安定期範囲 | turn安定期範囲 | seed通過 |
|---|---:|---:|---:|
| FORWARD | .596～.972 | 0 | 5/5 |
| TURN_R | 0 | +.471～+.717 | 5/5 |
| TURN_L | 0～.00445 | -1～-.664 | 5/5 |
| FORWARD_R | .518～1 | +.333～+1 | 5/5 |
| FORWARD_L | .649～1 | -1～-.283 | 5/5 |
| STOP最終窓 | 0 | 0 | 5/5 |

stable onset：F50ms、R100～150ms、L100ms、FR/FL100～150ms。
release→deadzoneは200～300ms。EMAなし同一校正対照に対し、first-correct onset差は
概ね0～100ms、releaseには100～200ms追加。Fに-50msの例があるのは、
共通filterがturn混入も抑えたためであり、非因果処理ではない。
実計算のstable onset約.39～1.25秒、STOP復帰約1.55～2.47秒。
**操作感のacceptanceは未完了。実験用採用であって即応ゲーム制御の完成ではない。**

controller組込み後、seed20261231の76frameを再実行しraw完全一致、motor最大誤差0。
TCP localhost30sampleも通過。E2E min711.78/mean788.21/median790.72/p95 799.03/max800.89ms。
brain step mean395.38/p95 400.96ms。frame到着間隔最大402.73ms、750ms超gap0。
未知Action/不正JSONをerror、2つ目の操作clientを拒否、20command burstで19件superseded、
最後のrequest適用、再接続でsequence継続・network1/reset0、切断後STOPを確認。
serverは一時起動して検証後停止。LAN/Windows実機は未実施。

Replay：Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl、76frame。
current nested motor/brainTimeMs形式、REPLAY metadata、ready=false。
Python側のschema照合は通過、Unity JsonUtility実行確認はWindows側に残る。
既存ReplayMotorSourceはperformance.stepWallTimeMsを再生時間に使うため、この記録は
脳内3.8秒だが実再生約29.9秒。既存仕様を変更せず正直な実測時間を保持した。

window benchmark（warm11、各first除外）：25ms mean202.28/p95 214.39、
50ms mean398.24/p95 414.32、100ms mean784.54/p95 799.13ms。
25/100msは性能のみ、6 Action意味の検証は50ms。serverは50msだけを受け付ける。
最終5seed記録runtime153.51秒、peak116,736,000 bytes、TCP観測RSS94,224,384 bytes。
全てmmap遅延読み込みを含む。全graphの常駐メモリとは扱わない。

model/weights/NT/populationは変更せず、ready=falseを維持。
Windows Replay読込、Windows Live接続、実ゲーム操作感は未完了。

## 実験設計

neural model、graph、production weight、NT policy、刺激条件、F/TURN populationは不変。
従来のdecoder出力も保持したままraw trajectoryを先に記録した。
50ms窓、初期STOP300ms、その後F/R/L/FR/FL各400msとSTOP各300ms。
各trial76窓、initialize1回（別途無刺激baseline100ms）、network resetなし。
各frameにはraw F/T、旧normalized値、DNa02/DNg100発火、population ΔV/gを保存。

探索seed20261211/12/13。FORWARD_Rのraw分類：

| seed | 分類 | turn_raw mV |
|---|---|---|
| 20261211 | A：8窓連続で正 | .0746～.3133 |
| 20261212 | A：8窓連続で正 | .0763～.3796 |
| 20261213 | B：初窓のみ負、その後7窓正 | -.1288～.4087 |

全窓ゼロではない。Bを単に「信号なし」とは解釈しない。

## 共通EMAと比較

`alpha=1-exp(-50/tau)`、raw F/Tの両軸へ同じcausal EMA。
フィルター状態はtrial開始時だけ0、Action遷移でresetしない。
decoderはraw2値とdtしか受け取らず、requestedActionを参照しない。
評価runnerだけがActionを正解ラベルとして使う。

τ100/150/200/300msを比較した。探索3seedの全gate通過数：

| 方式 | 100 | 150 | 200 | 300 |
|---|---:|---:|---:|---:|
| EMAのみ | 0/3 | 0/3 | 0/3 | 0/3 |
| EMA＋deadzone | 3/3 | 3/3 | 3/3 | 0/3 |
| EMA＋旧global2×2＋deadzone | 2/3 | 3/3 | 2/3 | 0/3 |

純F・純TURN・回復STOPの探索データだけからreference/thresholdを求めた。
combined探索データはτ/mode選択の成績に使い、Action専用係数には使わない。
同点なら単純な方式、短いτを優先。最初はEMA100＋deadzoneを固定した。
この段階で単純方式が通ったためhysteresisはまだ試していない。

## EMAの独立検証と追加段階

seed20261221～25：**4/5通過**。F/R/L/FLとSTOPは全通過、FRだけ4/5。
seed20261223でfiltered turnが .179→.159→.1068mVへ低下し、
deadzone .1121mVを最後の窓で下回った。8窓すべてのraw/filtered値は保存済み。
失敗を削除せず、final_validation.jsonとして保持する。

EMA不足が実測された後に限り、R/L対称turn-only hysteresisへ進んだ。
元の探索3seedだけでτ候補を再比較し、100msを選択。
turn ON=.1120717169mV、OFF=.0560358584mV。
OFF=max(ON/2,探索STOP第6窓の最大abs値×1.05)というglobal rule。
forwardは通常deadzone .0234514551mVのまま。
reference F=.2937641253mV、T=.3000467732mV。matrixはidentity、2D補正なし。
個別Action・個別neuron・左右別のparameterなし。

開始はabs(filtered turn)>ON、維持中は同符号でOFF超、OFF以下で解除。
出力はOFFを差し引いた連続値（固定値の符号強制ではない）。
反対符号の開始も同じ絶対ON閾値を用いる。
causal prefix一致、R/L符号対称、弱い信号維持、ゼロ入力からの自然復帰を確認した。

## 最終gateの定義

新しいseed20261231～35を用い、設定を固定して検証する。
各刺激の最後の4窓（200ms）で条件を連続維持することを要求する。
Fはforward>0かつturn deadzone内、R/Lは所定turn符号かつforward≤.15、
FR/FLはforward>0と所定turn符号。STOPは第6窓までに両出力0。
過渡期の誤符号を隠さず、first correctと、その後崩れないstable correctを別記録。
この観測長を超える任意長入力や別順序への保証ではない。

## 時間とメモリの解釈

latencyは50ms単位の脳内時間と、記録されたstepWallTimeMsの累積を分離する。
同一normalization/deadzoneでalpha=1とした対照も使い、EMAによる追加時間を比較する。
旧2D decoderのbefore-temporal値もraw recordに残す。
実時間にはTCP/Unity/E2Eは含まない。約400ms/脳内50msのモデルなので、
脳内100～300msは操作上無視できない実時間遅延となる。
RSSはmmapの遅延ページ読み込みを含むprocess値であり、全graph常駐サイズではない。

## 成果物・再現

Brain/MaleCNSのrecord_temporal_actions.pyで記録し、evaluate_temporal_decoder.pyで
探索と最初の独立検証。失敗後のみevaluate_temporal_hysteresis.pyを使用する。
summarize_temporal.pyで同一校正のEMAなし比較とlatencyを集計する。
記録phaseはcalibration / validation / validation_hysteresis。

`Docs/mac/checkpoints/temporal/`：rawはseed別JSON.gz、探索全設定、固定設定、
初回と最終の検証、latency summaryを保存。source/data-derived graph hash参照も含む。
seed番号は日付ではなく乱数識別子。
6 Actionの最終gate通過まではcontroller finalize/TCP/Replay/handoffに進まない。
ready=falseを維持する。
