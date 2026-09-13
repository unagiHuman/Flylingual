# MaleCNS 固定点最適化の検証

作成日: 2026-09-13。対象はWindows MaleCNSのfloat64 kernelである。
固定点最適化を実装し、3 seed・408区間で数値のbit一致を確認した。
直接比較は平均23.4%、p95約46.3%短縮。Windows実Brainと既存Native Playerの18操作も完了した。
精度を維持するため、固定点へ到達する途中の極小値演算は残している。すべての区間や最悪時間の改善を保証するものではない。

## 実装範囲

`lif_kernels.py`のg更新に、bitで判定する厳密固定点処理を追加した。
gのbit magnitude 0..25では、現行係数bとの積が丸め後に同値となるためgを保持する。
cとの積はsign XORからsigned zeroを生成する。
v更新のskipはvが厳密に-52の場合だけである。
それ以外のvは元のfloat64計算経路を維持する。
active更新を省略前に実行する。v=-52のままで発火しないことが確実な場合以外はfired判定も維持する。
delayed CSR、external input、reset、readout、loop順序は変更しない。
dt=0.1 ms、window=50 ms、500 tickを維持する。
N=166700、CSR保存entry E=19670694、観測readout=119である。
Eは保存edge数であり、毎tickに全Eを必ず処理する意味ではない。
FTZ/DAZは本番設定へ導入していない。
実行時の丸め・flush条件が固定点前提に適合しない場合はoriginal pathへfallbackする。
各kernel呼出しの最初に、実際の係数で±25qのb積が同じbit、c積が符号付き0となることを確認する（qはfloat64の最小subnormal）。aが非有限の場合も無効化する。
判定は整数bitで行い、DAZによる浮動小数点比較の変化を避ける。係数・丸め設定自体を書き換えない。
膜電位は-52近傍で丸め固定点となる場合もあるため、そのときは元の電位更新と加算を実行し、gの乗算のみ省略する。
神経状態・出力を一致対象とし、浮動小数点例外フラグの発生回数までの一致は保証しない。

## 直接検証条件

原本は[fixed-point/equivalence.json](../../artifacts/windows-malecns/fixed-point/equivalence.json)である。
seedは20270101、20270102、20270103の3種である。
各seedはinitial STOP 4窓、FORWARD 8窓、subnormal STOP 100窓、再刺激STOP 4窓、5 Action各4窓を含む。
合計はseedあたり136窓、全408 paired windowsである。
AB/BAをpaired windowごとに交互化し、初期化順もseedごとに交互化した。
kernel timerはrun_windowだけ、controller timerはPython準備・readoutを含む。
比較とhash保存はtimed callの外側で行った。
candidateとbaselineはloaded moduleの実ファイルpathを記録し、instanceを隔離した。

## 数値ゲート

numericGateはpass、408/408窓でexactだった。
v/g/last/rfc/tick、pending順序、count、RNG、decoder、観測値をbit比較し、状態hashも保存した。
BrainFrameはperformanceを除く項目を一致対象とした。
既存19件の小テストは9.068秒で全件pass、新規8件は1.728秒で全件passした。
新規テストは±0、±1〜25q、境界±26q、大きなsubnormal、最小normal、v隣接値、refractory、同tickのsynapse/刺激、刺激再開、record/window混在を含む。
別processで3種類の非nearest丸めとnearest＋flushの計4条件を試し、fallback・元演算とのbit一致・設定復元を確認した。検証でのみWindowsの[_controlfp_s](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/controlfp-s?view=msvc-170)を使用し、JITは通常環境で先に完了させた。
subnormal域、再刺激、STOP recoveryを含むが、全状態空間の証明ではない。
発火数とreadoutを保持し、値の近似や閾値変更は行っていない。

## 性能結果

baselineはn=408、controller wall平均165.445 ms、p95 330.975 ms、最大450.862 msだった。
candidateは平均126.783 ms、p95 177.605 ms、最大415.011 msだった。
平均wall短縮は約23.4%である。
kernel wallはbaseline平均164.286 ms、candidate125.609 msだった。
kernel thread CPUはbaseline156.059 ms、candidate119.332 msだった。
これは直接simulationの性能であり、TCP／Bridge／Unity E2Eではない。
初回JITを含むinitialization値はwarm window性能と分けて保存した。
RSSは各timed callのbefore/afterであり、長時間peakやリーク指標ではない。

### stage別の参考集計

| segment | n | baseline平均ms | candidate平均ms |
|---|---:|---:|---:|
| initial_stop | 12 | 102.420 | 95.297 |
| forward | 24 | 108.253 | 113.455 |
| subnormal_stop | 300 | 166.647 | 125.398 |
| restimulate_stop | 12 | 304.796 | 126.560 |
| restimulate_forward | 12 | 199.760 | 122.224 |
| restimulate_turn_r | 12 | 183.890 | 144.897 |
| restimulate_turn_l | 12 | 159.133 | 153.096 |
| restimulate_forward_r | 12 | 159.281 | 153.709 |
| restimulate_forward_l | 12 | 133.163 | 152.960 |

subnormal域のrestimulate STOPで改善が大きいが、segment平均を全実行条件へ一般化しない。
最後のSTOPの81〜100窓目（3 seed合計60窓）のkernel平均は297.990→122.085 ms、約59.0%短縮した。
一方、窓末にsubnormalがない246窓ではkernel平均106.902→114.838 msで、約7.4%遅い観測だった。今回の直接試験はCPU affinityを限定せず、コア差・外部負荷・分岐追加の影響を分離できない。全区間で一律に速いとは報告しない。
最大415.011 msが残ることも含め、過渡的なsubnormalに対する追加最適化は未実施。

## 無効にした試験

初回のsnapshot import比較`invalid-import-comparison.json`はmodule pathの分離が不十分で、採用根拠から除外した。
旧版のNumba cache互換headerがsys.pathへsnapshot directoryを挿入し、初回はcandidate側にも旧版が読み込まれた。数値・速度とも新実装の証拠として使用しない。
修正後はcandidateを先に読み、snapshotのsys.path変更を復元し、module実path・dispatcherの独立性・py_funcのsource pathとLIFへのbindingをassertした。valid reportのloadedKernelsに記録している。
本番source変更はkernelとhandoff manifest hashに限定される。

## Windows実Brain・同居Bridge・既存Native Player

[実機集計](../../artifacts/windows-malecns/fixed-point/native-evidence.json)、[Native summary](../../artifacts/windows-native-conversation/validation-20260913-100843/summary.json)、[計算profile](../../artifacts/windows-malecns/fixed-point/native-default/profile-summary.json)。

実行先127.0.0.1:18766、MALECNS_EXPERIMENTAL、ready=false。実会話サービス経由の文字指示による6 Action×3回を18/18適用した。マイク無効、Replay/mock/固定motorなし。CPU affinityは通常のままで、Pコア限定は今回の本番変更に含めていない。

| 計算profile | n | 平均 ms | p95 ms | 最大 ms |
|---|---:|---:|---:|---:|
| controller内stepWall | 520 | 174.155 | 260.308 | 308.882 |
| kernel wall | 520 | 162.535 | 242.771 | 281.074 |

profileはsession前後も含み、Unity受信frameの母数ではない。profileのsequenceは0〜519で連続進行し、計算750 ms以上は0件。Player summaryの最終sequenceは497、切断停止・自動再開なし・owned PID残留0、Player exception 0。controller呼出し全体のouter wallは平均185.763 msで、stepWallより広い範囲を測っている。profile観測自体の追加負荷も含むため、無計測時の保証値ではない。

118.750秒の実行でpeak tree RSSは993,357,824 bytes。最大移動変位は2.775e-7 mで、歩行の成功とは扱わない。Bridgeのmotor socket closeでConnectionResetErrorが記録されている。

前回通常profileの平均195.745 / p95 362.877 / 最大562.690 msより小さい観測だったが、別時刻・異なる負荷と指示履歴の試験であり、厳密な改善率として採用しない。今回のPlayerは試験開始前後でexe hashが一致した。本taskではUnityのbuild・編集は行っていない。

共有Bridgeイベントログはローテーションにより今回のbrain_identityを含む開始部分が失われ、E2E・完全な受信frame間隔・session metadata検査の再集計はできなかった。最新runtime directoryは別試験だったため使用せず、profile Brain PID 27472の親27272とbridge.logのlaunch PIDを照合してf884a164f8634ec4ac54eaaad28cbc62に対応付けた。欠測を0件や合格とは扱わない。マイク、15分連続、Mac、最悪時間保証も未検証。

## 変更ファイル・再現情報

- 本番: Brain/MaleCNS/lif_kernels.py。handoff manifestはrepoFilesのhashを更新し、旧hashをpreFixedPointRepoFileHashesに保存。ready/検証フラグを昇格していない。
- 検証: tools/test_malecns_fixed_point.py、tools/validate_malecns_fixed_point.py。
- 文書: 本書、Brain/MaleCNS/README.md。既存の他taskの変更は保持。commit/pushは未実施。
- baseline commit: eb6d3143131c5783dbed1657fcffb856166f03f3。
- kernel SHA-256: d0bb9c3fc7ef40ccd01769a1119f19ac92046672d2976f30a9a21ce5e172b116。
- source aggregate（ソースから計算）: 7551dbf610622af15be53ac8c33846d9be7a687e0455417ed3a7773843939e21。今回Native identityイベントは欠測であり、受信hashの照合済みという意味ではない。
- config SHA-256: 4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96。
- graph aggregate: dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569。4ファイルの個別hashは直接比較原本に保存。
- Python 3.10.12、NumPy 1.24.3、Numba 0.61.2、llvmlite 0.44.0、psutil 7.2.2。CPU i7-13620H、10物理/16論理、Balanced電源。

Flylingual rootからの実行コマンド。診断artifactはGit管理外でこのcheckoutに保存される。

```powershell
artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_window_compiled.py
artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_fixed_point.py
artifacts/windows-malecns/.venv/Scripts/python.exe tools/validate_malecns_fixed_point.py --output artifacts/windows-malecns/fixed-point/equivalence.json
.venv-bridge/Scripts/python.exe artifacts/windows-malecns/colocation-investigation/run_native_profile.py --output artifacts/windows-malecns/fixed-point/native-default
```

Native --outputは新規directoryが必要。診断hookのhash・sourceファイルhashは[metadata](../../artifacts/windows-malecns/fixed-point/native-default/metadata.json)、Player exeの前後hashは[Player provenance](../../artifacts/windows-malecns/fixed-point/native-player-provenance.json)に保存した。

## 参照

- [fixed-point equivalence](../../artifacts/windows-malecns/fixed-point/equivalence.json)
- [colocation latency investigation](./M1-malecns-colocation-latency-investigation.md)
- [compiled kernel validation](./M1-malecns-compiled-kernel-validation.md)
- [runtime source](../../Brain/MaleCNS/lif_kernels.py)
