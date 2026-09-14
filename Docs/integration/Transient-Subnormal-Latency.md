# 過渡subnormalの数値不変最適化

2026-09-14。**数値同等性・境界テスト・延長した日英実Player試験はPASS**。以前の約1秒の遅延区間を数値不変で短縮し、今回の操作・監視区間では制御喪失を検出しなかった。正本は [共通設計](../Brain-GPTLive-CrossPlatform-Design.md)、発端は [質問後接続検証](Question-Connection-Validation.md)。

## 修正の理由と境界

旧 `question-connection-ja/en` ではmeanGがsubnormalになる区間と、約1秒のBrain step遅延が一致した。既存最適化はconductanceの絶対bit magnitude 0..25の固定点を保存して計算を省略するだけで、26以上の過渡subnormalでは乗算が残っていた。この一致だけからCPU遅延の全内訳を断定しない。

`lif_kernels.py` の新経路はsubnormalをゼロ化しない。subnormalを整数m×2^-1074、0.5≤b<1を整数B×2^-53で表し、m×Bを32bit limbに分割して全bitを保持する。2^53で除した商・余りからround-to-nearest, ties-to-evenを厳密に求め、元の符号bitを復元する。浮動小数への中間スケーリングや二重丸めは行わない。

係数と環境のguardは既存の±25固定点bit probeを使用し、FTZ/DAZや非互換な丸めを拒否する。追加条件は0.5≤b<1、|c|≤1。対象外は元の乗算経路へ戻す。通常normalのg減衰も元の乗算を維持する。

電位更新のx計算順は変更しない。|g|≤2^-1007（絶対bit magnitude≤0x0100000000000000）、|x|≥1では|g×c|が半ULPより十分小さく、xへの加算結果を変えないため、この微小積を省略する。小さいxでは元の積を計算する。signed zero、refractory、発火順、遅延CSR配送、観測sumを保存する。fastmath、刺激条件、神経数値、decoder、750ms stale閾値、Unity物理、ready=falseは変更しない。

## 確定したpaired検証

原本：`artifacts/windows-malecns/transient/equivalence.json`。complete=true、numericGate=pass、tcpUnityGate=not measured。baselineは `50d4825`。

- seeds：20270101、20270102、20270103。408 paired窓、N=166700、E=19670694、dt=0.1ms、窓50ms。
- 全state、pending、count、RNG、decoder、数値BrainFrameをbit一致比較。frameのperformanceだけを数値比較から除外。
- AB/BA順序を窓ごとに交替。controller wall p95はbaseline182.148ms→candidate157.452ms、max329.140ms→239.666ms。process CPU平均119.677ms→115.388ms。
- report内のrssAfterBytes最大はbaseline166014976、candidate165773312。これは記録対象processの窓後サンプルであり、全process合計や瞬間peakの証明ではない。

Python3.10.12、NumPy1.24.3、Numba0.61.2、llvmlite0.44.0、psutil7.2.2。candidate kernel SHA256は `84baf513347e9b51d8df88aa43844ebf749d83616bbb14d08dcb8104ccfc1da6`、config SHA256は `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。graph4ファイル、baseline/candidate source、validatorの全hashは原本reportに保持する。平均・p95の改善を全状況の最大遅延保証へ拡張しない。

## 境界試験とPlayer試験の条件

既存fixed-point境界8件PASS（3.226秒）、新transient境界4件PASS（0.587秒）。独立Python任意精度積oracle、NumPy演算順oracle、両符号subnormal、normal指数1..16とtiny上限±1、実中間x=±1前後、非互換係数fallbackを対象とする。乱数標本は全mantissaの網羅ではない。既存試験ではWindowsの方向丸めとFTZも別processで確認した。

先行 `transient-connection-ja/en` は両方connection_stability_pass、制御喪失0／epoch変化0、再移動とSTOPを確認した。日本語ではseq253..256の過渡領域を304／316／315／307msで通過。英語では過渡領域への到達がcleanup後にずれたため、単に先行PASSだけで終了せず、ProbeのSTOP後監視を8秒延ばして再検証した。ゲーム本体の停止条件や待機ペナルティは変えていない。

延長版のUnity compileはcompleted、errors=[]、compilationFailed=false。Dev-Local buildは13:00:18→13:00:40 UTC、Succeeded。BuildReportの1 errorはCLIの応答5秒timeoutであり、ビルド失敗とは分けて確認した。Playerは正式rootの更新Pythonを起動する。

```powershell
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_fixed_point.py
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_transient.py
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/validate_malecns_fixed_point.py --baseline-ref 50d4825 --output artifacts/windows-malecns/transient/equivalence.json
& tools/neural_player_trial.ps1 -Name transient-extended-ja -Language ja -Question 0 -ConnectionStability
& tools/neural_player_trial.ps1 -Name transient-extended-en -Language en -Question 0 -ConnectionStability
```

## 延長した実Playerの結果

確定結果を以下に記録する。接続先は127.0.0.1:18766、MALECNS_EXPERIMENTAL／LIVE、ready=false。許可済みの合成テキストと実GPT Live/APIを使い、マイク入力はない。

原本は `artifacts/neural-feedback/transient-extended-{ja,en}*` のPlayer JSON、Bridge全ローテーション、Player log、metrics。source hashは `transient-extended-source-hashes.json`、先行試験は `transient-source-hashes.json` に保存した。Brainの神経刺激設定のhashは [前段の実測](Visual-Threat-Game-Integration.md) と同じで、今回変更していない。

| 観測 | 日本語 extended | 英語 extended |
|---|---:|---:|
| result | connection_stability_pass | connection_stability_pass |
| 制御喪失 / epoch変化 | 0 / 0 | 0 / 0 |
| 再移動 / 最終STOP / fresh | true / true / true | true / true / true |
| 質問後の変位 | 2.281m | 2.290m |
| Player観測seq | 26→313 | 18→306 |
| Player frames / neuralFrames | 306 / 303 | 298 / 296 |
| 保存Bridge frames / seq | 316 / 2→317 | 309 / 3→311 |
| 保存Bridge観測時間 | 55.187秒 | 54.421秒 |
| Brain step p95 / max | 270.370 / 359.544ms | 283.377 / 343.653ms |
| Unity frame p95 | 16.779ms | 16.694ms |
| Player sampled peak RSS | 574,955,520 bytes | 573,513,728 bytes |
| 質問後FORWARD送信→適用 | 500ms | 328ms |
| 通常STOP送信→適用 | 641ms (seq276) | 453ms (seq271) |
| errorフィールド | 空 | old_conversation_generation |

Playerのp95と上表のBrain p95は昇順のfloor((n−1)×0.95)位置（補間なし）。paired validatorのp95はNumPy線形補間であり、算出法を区別する。Bridge観測時間は保存先頭frameから末尾frameまでで起動全時間ではない。両Playerはexit 0、果汁接触・警告開始・解除各1、感覚ON/OFFとDNp01応答を観測した。合格判定はerror文字列の空判定ではなく、fresh・STOP・移動・神経応答と制御喪失0／epoch変化0による。

日本語の感覚入力後の過渡はseq273..276付近で、seq273..275は326.260／309.458／338.900ms。英語はseq271..273で304.898／343.653／317.588ms、最小meanGが1.204e−309→2.482e−318へ減衰した。いずれも監視終了seq313／306より前で、その後の固定点尾部まで観測した。旧試験の同領域は約755〜1083msだった。実Player同士はAPI時刻・入力窓数が完全同期したpaired数値比較ではなく、数値同等性の証拠は別の408 paired窓である。

観測後のNativeSTOPは日本語seq313、英語seq306のcleanupに対応する。操作中はepoch3を維持し、最初の終了側inhibitはconversation_stopped。意図的な終了ログをプレイ中の接続障害と混同しない。英語のerror文字列 `old_conversation_generation` は保存したままで、発生元の個別メッセージは今回の保存ログから確定していない。全エラーなしとは報告しないが、移動・STOP・接続維持への影響は検出しなかった。

## 範囲と残る確認

この修正は観測した減衰遅延と約55秒の試験経路への対応であり、全負荷・無期限連続接続を保証しない。マイク操作、耳での音声品質、会話の自然さ、目視の操作感、ゴールまでの長時間プレイは別途確認する。神経感情・学習・回避成功を測定できたとの主張は追加しない。設定定義・刺激・ready判定・750ms安全基準は変更していない。
