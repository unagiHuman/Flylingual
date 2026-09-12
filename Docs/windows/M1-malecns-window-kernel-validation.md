# MaleCNS window・シナプス伝達コンパイル化の検証記録

2026-09-13。500 tickのLIF処理と遅延シナプス伝達をコンパイル化した。
同条件の直接比較では前段実装から平均9.934%短縮し、検証範囲の数値は完全一致した。
ただし、Unity同居試験は前回より遅い結果となり、同居時の高速化は確認できていない。

## 採用した実装

- `lif_kernels.run_window` がstate更新、発火、18 tick遅延のCSR伝達、外部入力、reset、観測値加算を500 tick繰り返す。
- float64、dt=0.1 ms、50 ms window、加算順序を維持。CSRは元のedge順に逐次加算し、重複targetも順序を変えない。
- Pythonの既存Generatorを各tickで同じ順に消費し、入力列をoffset/index配列として事前生成する。神経状態に依存する入力生成への変更はない。
- 19 slotの数値ringと既存pending listを窓境界で同期する。診断用の`step(record=True)`を維持し、両経路の交互使用も検証した。
- 不正offset/index/count bufferをnative実行前に検証。初期化時の0 tick呼び出しでwindow署名をREADY前に準備する。
- decoder、刺激条件、神経数・結合、Unity・物理設定は変更していない。NumPy 1.24.3、Numba 0.61.2、llvmlite 0.44.0を維持した。

## 最終版の直接比較

[最終比較原本](../../artifacts/windows-malecns/window-compiled/equivalence.json)の三者168区間比較。
各値は同じ実行内の測定であり、前回の別時刻の絶対値と混ぜない。

| 実装 | 平均 ms | 中央値 ms | p95 ms | 観測最大 ms |
|---|---:|---:|---:|---:|
| 最初のNumPy版 | 536.334 | 507.721 | 679.076 | 820.101 |
| 前段のニューロン更新コンパイル版 | 112.479 | 104.458 | 154.663 | 206.258 |
| 今回のwindow版 | 101.305 | 95.551 | 134.074 | 169.748 |

前段比で平均9.934%、p95約13.3%短縮した。50 ms分の脳内時間を常に50 ms以内で処理する水準には達していない。

比較基準はNumPy版`add036414f262c8f35dd289d42bc150e7d699525`、前段版`88d117d02dc72710de893590811669bb9fccc2d0`。
後者の3ファイルは作業開始時snapshotとSHAが一致することも確認した。
validatorは既定で固定commitから基準を読み、`--snapshot-dir`指定時だけ一致するsnapshotを使う。

- seed: 20270101、20270102、20270103。
- 各seed: STOP、FORWARD、TURN_R、TURN_L、FORWARD_R、FORWARD_L、STOPの7区間、各8 window。各arm n=168。
- N=166700、CSR保存entry E=19670694、観測対象119。Eは毎tickに全件走査する数ではない。
- 実行順はABC/CBAを交互化。計測内のcount参照取得wrapperは旧経路500回・新経路1回であり、この差を含む。
- 配列比較、hash、JSON保存、LLVM検査は計測外。RSSは三者が常駐するprocessの前後値で、arm別RSSやpeakではない。
- 初回呼び出し・初期化とwarm windowを分離した。通常計測はdisk cacheが空の状態を保証しない。

## 数値・キャッシュ回帰

19小テストが6.826秒で全件成功した。全graphの168窓では、窓境界のv/g/last/rfc/tick、count、pending順、RNG、decoder状態、BrainFrameのperformance以外がbit一致した。
小graphではthreshold、refractory、18 tick遅延、ringの周回、重複・打消し加算、外部入力とreset、record経路との交互使用を確認した。
旧4096 neuron試験はtickごとの比較、新2048 neuron試験は最大500 tickまでの複数prefixと観測値加算順を比較する。
Generatorの各tickの刺激列そのものと最終状態も比較した。全seedの最終STOPは8窓でmotor near-zeroが3窓以上連続した。
これは全入力についての証明や全network silenceの判定ではない。

実機初回`validation-20260913-005130`では、Numbaキャッシュのimport名がpackage形式で記録され、standalone起動時に`ModuleNotFoundError: Brain`となった。
Probe Aのpackage importで露呈したもので、[起動診断原本](../../artifacts/windows-malecns/window-compiled/startup-diagnostic.txt)を残した。BrainFrame 0件、残留owned PID 0件。
`lif_kernels.py`でmodule directoryとrepo rootをimport可能にし、両経路のキャッシュ復元を修正した。キャッシュ削除で対処していない。
数値関数のASTはこの修正前後で同一だが、修正後ソースで上記の三者比較も再実行した。

[キャッシュ回帰原本](../../artifacts/windows-malecns/window-compiled/cache-entrypoint-regression.json)では、隔離したcache directoryと別processでpackage→standalone、逆順の両方向を検証。
helper・run_windowとも初回miss=1/hit=0、復元時hit=1/miss=0、数値bits一致を確認した。
最終版のneuron-update 1署名・run_window 2署名はnopythonで、LLVM/assemblyのfast/reassoc/contract・FMA検出は0だった。

## Windows実Brain・Bridge・既存Native Player

[実機集計](../../artifacts/windows-native-conversation/validation-20260913-010100/performance-analysis.json)、[summary](../../artifacts/windows-native-conversation/validation-20260913-010100/summary.json)、[Brain/command原本](../../artifacts/windows-native-conversation/validation-20260913-010100/brain-evidence.jsonl)。
Windows localhostの実Brainを使用し、既存Native Playerで実際の会話サービスへの文字指示から6 Actionを各3回適用した。マイク入力は無効。

- Brain `127.0.0.1:18766`、Bridge `127.0.0.1:18770/18771`、MALECNS_EXPERIMENTAL、LIVE、ready=false。
- 18/18操作適用、sequence進行、metadata不一致0。意図的なTCP切断後に停止し、自動再開なし。
- BrainFrame n=528。compute平均186.888 ms、p95 323.755 ms、最大671.105 ms。
- frame間隔 n=527。平均187.471 ms、p95 328 ms、最大671 ms。compute/間隔とも750 ms以上0件。
- Bridge送信→Brain適用のE2E n=37。平均331.378 ms、p95 659.2 ms、最大1046 ms。音声入力・意図翻訳時間は含まない。
- 起動READY 2000 ms、trial全体125.844秒、peak process-tree RSS 983183360 bytes。
- Player例外0、owned PID残留0。Bridge終了・controller解放と同時刻に`ClientConnectionResetError`のbackground_failedが1件記録された。これを無エラーとは報告しない。

検証runnerは`native_actions_transport_pass`だが、性能目標のp95 compute≤250 ms、観測最大≤500 ms、E2E p95≤500 msは今回未達。
前回の別trialはcompute平均158.313 ms、p95 268.155 ms、最大321.920 msだったため、今回の同居性能改善は未確認である。
別時刻・異なる進行のtrialなので、差の原因をkernel変更やCPU競合に断定しない。遅い回の原因切り分けが残る。
移動Actionの変位は最大2.747e-7 mであり、実歩行達成とは扱わない。15分継続、Mac、実マイク、新Unity buildも未検証。

## 採用しなかった構造

[初版比較](../../artifacts/windows-malecns/window-compiled/initial-candidate/equivalence.json)は平均8.822%改善・18小テスト成功。上記最終値とは別実行の試作履歴である。
[追加probe](../../artifacts/windows-malecns/window-compiled/probes/results.json)では1 seed・14窓を比較した。
同一比較内の平均は初版96.579 ms、既存kernelをnative callするAは99.727 ms、state/firedを分離するBは102.500 ms。
A/Bとも18小テストと14窓の数値一致は成功したが遅かったため不採用。Bではpacked SIMD演算が生成されても速度改善につながらなかった。

## 追跡情報・再実行

Python 3.10.12、Windows AMD64。依存版、各source/data/config SHA、CPU時間・RSS・署名は比較原本に保存した。
最終kernel SHA: `adfb3ab1f18e82a9b4cc2c3883f95e789e583fd094df19a1afa1128d68f3cbce`。
実機と現行sourceのaggregate SHA: `fb41f208472c5406c79d0c9808b9c54f19b9162ec0815bccc2c714c2f306d3e2`。
config aggregate: `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。
graph aggregate: `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`。

manifestの3 runtime SHAを更新し、以前の値を`preWindowCompiledRepoFileHashes`に保存した。ready=falseとwindowsLiveVerified=falseを維持。
Windows-local doctor、graph 4ファイルとrepo hash検証、launcher 13テストも成功した。

Flylingualルートで実行（固定依存、Git基準履歴、実graph assetsが必要）。

```powershell
artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_window_compiled.py
artifacts/windows-malecns/.venv/Scripts/python.exe tools/validate_malecns_window_compiled.py --output artifacts/windows-malecns/window-compiled/equivalence.json
.venv-bridge/Scripts/python.exe tools/verify_native_player.py --cycles 1 --no-microphone --actions
```

Native試験には既存Playerと通常の会話サービス接続設定が必要。再実行の実測値がこの記録を自動的に再現するとは限らない。
