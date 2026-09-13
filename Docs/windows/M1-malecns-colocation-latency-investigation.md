# MaleCNS Windows同居遅延の調査

2026-09-13。新たな実測で、遅延の大部分が神経計算kernel内にあることを確認した。特に、減衰したgがsubnormal（極小の非正規化数）として残るとCPU時間自体が増える現象を、Unityなしでも再現した。P/Eコアの性能差も確認できた。過去の750 msや671 msを単一原因へ完全に帰属できたわけではない。

本番ソース、float64、dt、乱数、graph、decoder、ready、Unity物理、電源・優先度の恒久設定は変更していない。診断用processだけaffinityを変更し、終了・復元を確認した。変更成果はこの文書とignored artifacts内の診断スクリプト・結果。commit/pushは実施していない。

## 1. 長時間動作で残るsubnormalが有力な原因

[直接診断原本](../../artifacts/windows-malecns/colocation-investigation/denormal-results.json)では、実際の全graph controllerをPコアに限定し、STOP 4窓→FORWARD 8窓→STOP 100窓を実行した。seed=20270101、1窓50 ms、dt=0.1 ms。神経値を一切変更せず、各step後にgのbit列を読み取った。

| 最終STOPの状態 | 母数 | kernel平均wall ms | kernel平均thread CPU ms |
|---|---:|---:|---:|
| 窓の前後ともsubnormalなし | 69 | 97.948 | 97.373 |
| 窓開始時点でsubnormalあり | 30 | 237.287 | 229.167 |

初出の移行窓1件は表の両群から除いた。STOP 70窓目、brainTime=4200 msで1167個がsubnormalになった。75窓目には4307個がbit `0x19`（25×最小subnormal、約1.24e-322）で残留し、100窓目まで変わらなかった。発火0・motor0のまま、kernel平均wallは約2.42倍。subnormal数とkernel CPU時間の相関はr=0.984だった。

現行の `g *= exp(-0.1/5)` は、g=1から約3.54秒の脳内時間で最小normal付近まで減衰する。さらに丸めによって極小の非ゼロ値で減衰が止まり得る。`lif_kernels.run_window` はその状態でも各窓166700ニューロン×500 tickを走査し、v/gの乗算を繰り返す。subnormal演算が通常値より遅くなり得ることは[Intel公式資料](https://www.intel.com/content/www/us/en/docs/dpcpp-cpp-compiler/developer-guide-reference/2024-2/denormal-numbers.html)とも整合する。

従来の三者168窓試験はseedごと2.8秒、今回のP/E比較も1.4秒の脳内時間だった。数値一致の検証は有効だが、この経過域での速度悪化を十分に覆っていなかった。

実際の同居Pコア試験でも同じ残留を確認した。[状態profile集計](../../artifacts/windows-malecns/colocation-investigation/native-p-state/profile-summary.json)の最遅sequence 484はSTOP、発火0、g subnormal 5008個、kernel wall 300.374 ms、thread CPU 296.875 msだった。STOP 330窓でsubnormal数とkernel CPU時間の相関はr=0.947。これは直接診断を支持する。ただし、ハードウェアassist counterは未測定で、過去の最大遅延の全成分を証明するものではない。

## 2. P/Eコアによる差

CPUはIntel Core i7-13620H、10物理・16論理コア。Windows CPU SetのEfficiencyClassを読み、論理0..11をP、12..15をEと分類した。高いEfficiencyClassほど高速・低電力効率側である。[Microsoft定義](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_cpu_set_information)

[28窓の同一入力比較](../../artifacts/windows-malecns/colocation-investigation/cpu-class-results.json)は、同じ実graph・seedでP/EをAB/BA交互実行した。

| 実行コア | 平均wall ms | p95 wall ms | 平均thread CPU ms |
|---|---:|---:|---:|
| P | 102.807 | 111.757 | 99.330 |
| E | 166.661 | 175.538 | 164.621 |

E/Pは約1.62倍。全28窓で神経状態・count・pending・乱数・decoder・performance以外のframeが一致した。自己processのaffinity復元も確認済み。

通常同居profileでは開始・終了ともPだった窓222件、E 80件、P/Eをまたぐ端点199件だった。端点のみなので途中の実行コア履歴は分からない。通常profileの各群は入力・状態が異なるため、それだけで因果効果を計算しない。

## 3. 通信待ちとCPU計算の切り分け

[通常profile集計](../../artifacts/windows-malecns/colocation-investigation/native-default/profile-summary.json)は501窓。平均step wall 195.745 msに対し、kernel wall 192.843 ms（平均値の比で98.5%）、kernel thread CPU 184.101 msだった。kernel内のwall−CPU差は平均8.742 ms。window内のその他処理は0.366 ms、controllerのwindow外処理は2.843 msだった。

最遅sequence 301のstepは562.690 ms、kernel wall 561.171 ms、kernel CPU 531.25 ms。遅延の大半は実行中の神経計算にあり、TCP送信待ちがstepWallを直接引き延ばす構造ではない。kernelはnogilの逐次計算で、Pythonへの500回往復も既に除去されている。[kernel](../../Brain/MaleCNS/lif_kernels.py)、[worker](../../Brain/MaleCNS/brain_server_analog.py)

workerは窓境界で最新commandを取り出し、次の窓を計算してから適用frameを送る。このためBridgeでの指示反映時間は「現在の窓の残り＋新しい窓の計算＋配送」を含む。E2E最大1016 msを通信待ち1秒と解釈できない。E2Eの計測点はBridgeのcommand submitted→appliedで、GPT推論全体や物理動作完了の時間ではない。

thread CPUは対象threadのCPU実行時間であり、今回のWindows記録には約15.625 msの量子化がある。個々の窓でwall−CPUが負になる場合もあるため、細かい差の断定を避けた。[Pythonの定義](https://docs.python.org/3.10/library/time.html#time.thread_time)

同居監視ではUnity、Chrome、ChatGPT、MsMpEng等のCPU利用を確認した。ただし51 sample/約105秒のtop-process集計であり、個別の遅い窓を特定processへ帰属できない。動的クロック、温度、電力、cache miss、メモリ帯域、ETW schedulingは未測定。Balanced電源プランは読み取りのみで変更していない。

## 4. Windows実Brain→Bridge→既存Native Playerの結果

接続先はWindows localhost `127.0.0.1:18766`、backendはMALECNS_EXPERIMENTAL、datasetはmale-cns:v1.0、mode=LIVE、ready=false。実会話サービス経由の文字指示で6 Action×3回、マイク無効。Replay/mock/固定motorは使用していない。

| 試験 | 受信frame | step平均 / p95 / 最大 ms | Bridge applied E2E平均 / p95 / 最大 ms | 操作 |
|---|---:|---|---|---|
| 通常 [012033](../../artifacts/windows-native-conversation/validation-20260913-012033/performance-analysis.json) | 499 | 196.136 / 363.361 / 562.690 | 361.000 / 578.000 / 1016.000（n=37） | 18/18 |
| P限定初回 [012350](../../artifacts/windows-native-conversation/validation-20260913-012350/performance-analysis.json) | 294 | 117.093 / 192.696 / 242.618 | 186.429 / 278.750 / 360.000（n=14） | 6/18、不完了 |
| P限定＋状態観測 [012931](../../artifacts/windows-native-conversation/validation-20260913-012931/performance-analysis.json) | 602 | 148.043 / 236.985 / 301.837 | 252.895 / 424.400 / 453.000（n=38） | 18/18 |

通常とP限定再試験の観測差は平均約24.5%、最大約46.4%短縮。ただし1回ずつで、指示到着時刻・窓数・神経履歴・外部負荷が同一ではなく、再試験は状態読み取り観測も追加した。この割合を恒久的な改善保証やaffinityだけの厳密な効果にはしない。状態profileは604窓で、session前後も含むため受信602 frameと母数が異なる。

完了した2試験ではsequence増加、metadata error 0、step/frame gapの750 ms以上0、切断時停止・自動再開なし、残留owned PID 0、Player exception 0。通常のframe間隔は平均197.006 ms・最大563 ms、P再試験は平均149.466 ms・最大312 ms。通常は終了時ClientConnectionResetErrorが1件、P再試験はbackground failure 0。観測時間は104.672 / 96.062秒、peak tree RSSは1,006,374,912 / 1,004,990,464 bytes。

P初回は40.984秒・6/18後にbody_fixed_tcp_disconnectedで終了した。直前frameAge 133.6 ms、serverAge 147.8 ms、command_expired 1件。切断の根本原因をCPU遅延と断定できず、この試験は合格や全体改善率の根拠に使っていない。残留owned PIDは0。

これは輸送・指示適用の検証であり、実歩行の成功ではない。移動指示での最大変位は通常2.606e-7 m、P再試験2.313e-7 m。マイク、15分連続動作、750 ms以下の最悪時間保証は未検証。

## 5. 精度を維持する次の対策候補

優先候補は、丸め後にv/gが変わらない固定点だけをbitで判定し、値を保持したままその浮動小数演算を省くこと。現行係数・nearest-even・gradual underflowなら、v=-52かつgの絶対bit値が最小subnormalの1〜25倍では、g*bは同じ値、g*cは符号付き0になる。26倍は対象外。active更新、遅延synapse、外部刺激、reset、観測加算は維持する必要がある。

これは設計候補で未実装。±0、±1〜25、境界26、v隣接値、refractory境界、同tick入力、刺激再開、record/window混在、長い全graph比較、実行時丸めモード・生成コードの検証が必要。浮動小数例外フラグの発生まで等価とは限らない。FTZ/DAZや極小値のゼロ切捨ては状態を変えるため採用していない。

Pコアへの実行配置も候補だが、端末固有の0..11を本番へ直書きせず、CPU topologyと他processへの影響を考慮する。今回の結果から、まず通信最適化よりもsubnormal固定点対策と実行コア配置を優先する根拠が得られた。

## 診断の検証と再現情報

[hook検証](../../artifacts/windows-malecns/colocation-investigation/profile-validation.json)は14 paired窓で神経状態・乱数・出力が一致し、sidecar 14件/error 0。正常なBrain entrypointへの自動導入も確認した。時間差はばらつきが大きく、overhead上限は確定していない。count.sumはwire/outer内、JSON write/flushはその外。再試験ではgの読み取りをouter終点の後に追加し、追加観測平均0.706 ms・最大1.978 ms、最初のJSON record write/flush平均0.086 msだった。後者は二つ目の記録のflush時間を含まず、総overheadではない。cacheへの観測影響も否定しない。

本番3ファイルのSHA-256は全試験で一致。runtime aggregateは各Native identityから確認した。

- source: `fb41f208472c5406c79d0c9808b9c54f19b9162ec0815bccc2c714c2f306d3e2`
- config: `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`
- graph: `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`
- N=166700、保存CSR entry E=19670694、観測119。全CNSの実データを使用し、E全件を毎tick走査しているわけではない。
- Python 3.10.12、NumPy 1.24.3、Numba 0.61.2、llvmlite 0.44.0、psutil 7.2.2。

以下はFlylingual rootから実行。各--outputは新規directoryが必要。通常試験は最初のコマンドでnative-default、P初回は最後のコマンド相当でnative-p-onlyを使用した。診断hookの版は各metadataにhashを保存し、状態観測追加前後を区別している。

```powershell
.venv-bridge/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/run_native_profile.py --output artifacts/windows-malecns/colocation-investigation/native-default
artifacts/windows-malecns/.venv/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/validate_profile.py
artifacts/windows-malecns/.venv/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/cpu_class_probe.py
artifacts/windows-malecns/.venv/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/denormal_probe.py
.venv-bridge/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/run_native_profile.py --output artifacts/windows-malecns/colocation-investigation/native-p-state --affinity 0,1,2,3,4,5,6,7,8,9,10,11
```

[通常metadata](../../artifacts/windows-malecns/colocation-investigation/native-default/metadata.json)、[P再試験metadata](../../artifacts/windows-malecns/colocation-investigation/native-p-state/metadata.json)、[計測hook](../../artifacts/windows-malecns/colocation-investigation/hooks/brain_profile.py)、[直接診断script](../../artifacts/windows-malecns/colocation-investigation/denormal_probe.py)に詳細を残した。診断artifactはGit管理外であり、このcheckoutに保存される。
