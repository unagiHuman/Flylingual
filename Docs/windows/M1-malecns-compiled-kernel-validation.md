# MaleCNS compiled kernel 検証記録

作成日: 2026-09-13。対象はFlylingualのWindows MaleCNS runtimeである。
本記録はcompiled kernelの数値一致、直接計測、実Brain＋Bridge＋既存Native Playerの通信・適用試験をまとめたものだ。
実歩行の合格や15分継続の合格を意味しない。

## 実装状態

`Brain/MaleCNS/shiu_compatible.py` は `lif_kernels.py` のserial `njit` kernelを呼ぶ。
kernelは `cache=True`、`fastmath=False`、`nogil=True`、nopythonである。
float64のstate更新、active判定、fired判定をfused処理する。
現行の演算順を保持し、FMA/reassociationを許可していない。
後段の `np.add.at`、reset、delayed delivery、readout、decoderは変更していない。
NumPy 1.24.3は維持した。
実行環境はPython 3.10.12、Numba 0.61.2、llvmlite 0.44.0である。
Numbaはruntime必須であり、未導入時にNumPyへ黙ってfallbackしない。
requirements-runtimeには固定versionを記録した。
初回JITのcold compileはbaseline initialization内でREADY前に行われる。
source hashの対象には `lif_kernels.py` を追加した。
manifestはcandidate hashを保持し、旧hashは `preCompiledRepoFileHashes` に保存した。
別commitのneural visualization変更は3箇所のhash整合を維持している。
`ready=false` は維持する。

## 比較条件

比較はbaseline commit `add036414f262c8f35dd289d42bc150e7d699525`を固定した。
計測HEADは `f6e97634c8fb15714e48f27d122f1c61b92c6f43` である。
計測時の独立visualization設定は `visualization_atlas=None` とした。
baselineとcandidateは同じcount-reference capture wrapperをtimed call内で通した。
hash保存、配列比較、JSON保存はtimed callの外側に置いた。
AB/BA順を全paired windowで交互化した。
seedは20270101、20270102、20270103である。
各seedはSTOP、FORWARD、TURN_R、TURN_L、FORWARD_R、FORWARD_L、STOPの7区間である。
各区間は8 window、合計168 paired windowsである。
dtは0.1 ms、windowは50 msである。
N=166700、CSR保存entry E=19670694、観測readoutは119である。
Eは保存edge数であり、毎tickに全Eを処理するという意味ではない。

## 数値ゲート

`artifacts/windows-malecns/compiled/equivalence.json` のnumericGateはpassである。
全graphの168窓ではwindow境界のstate配列、decoder状態、RNG、pending ordering、BrainFrame非timing項目が一致した。
10件の小テストのうち4096ニューロン×3 seed、record=False/Trueではtick単位のv、g、last、rfc、spikes、countも比較した。
BrainFrameの除外項目はperformanceだけである。
compiled kernelのLLVMはfast floating flags 0である。
FMA instructionとFMA intrinsicは0である。
10件の小テストも全件成功し、failure 0、error 0である。
STOPは全seedで8窓以内にnear-zeroへ収束した。
最終STOPでは全seedで3回以上のnear-zero連続を確認した。
最後のmotor zeroは数値記録として保存したが、全network silenceとは別である。

## 直接性能結果

baselineはn=168、平均487.992 ms、p95 526.694 ms、観測最大561.459 msである。
candidateはn=168、平均105.695 ms、p95 114.971 ms、観測最大119.571 msである。
この比較は直接simulationの性能であり、TCPまたはUnity性能gateではない。
性能gate自体はJSONで未評価扱いである。
初回constructorとkernel初回呼び出しはwarm full-graph時間から分離して記録した。
LLVM検査用の明示的な再compileもwarm計測の外側で行った。
Numba disk cacheが既に存在する可能性があり、machine-wide cache-coldの保証はない。
RSSは両controller常駐中のprocess RSSで、peak RSSではない。
したがってこの結果だけから長時間安定性やメモリリークを主張しない。

## 休眠skip案の扱い

厳密静止ニューロンskipはrest-probeだけで試作した。
productionには入れていない。
14 paired windows、seed 20270101、各区間2窓の探索結果はnumericGate passだった。
しかしcurrent compiled平均106.373 msに対しexact-restは132.141 msだった。
平均で24.22%遅く、p95は112.263 msから147.645 msへ悪化した。
したがって現時点では採用しない。
productionModifiedはfalseである。

## 実機と未測定範囲

指定Unity 6000.5.5f1はこのPCで解決できず、BuildDemoはeditor解決で停止した。
UnityProjectは変更せず、版のアップグレードも行っていない。
旧m1 Playerには `-liveRefreshInput` がなく、既存native Playerはdefineの違いで従来trialへ流用できない。
既存 `verify_native_player.py --cycles 1 --no-microphone --actions` の最初のsandbox試験は外部会話接続失敗である。
Brain自体は接続済みで、起動時間1.203秒を確認した。
この失敗をkernel性能の成功またはUnity合格へ読み替えない。
sandbox外で同じ既存検証スクリプトを再実行した結果を次節に記録する。
`ready=false` は維持する。

## 2026-09-13 実Brain＋既存Native Player試験

親担当が同じ `tools/verify_native_player.py --cycles 1 --no-microphone --actions` をsandbox外で再実行した。
原本は `artifacts/windows-native-conversation/validation-20260913-002239/` に保存されている。
これは新しいC# buildではなく、以前750 ms超過で停止した既存Native Playerを実Pythonへ接続した試験である。
指定Unity 6000.5.5f1の新規buildは未実施であり、Unity設定・物理設定も変更していない。

BrainFrameは579件、sequence増加、metadata mismatch 0、compute>=750 msは0件、frame gap>=750 msも0件だった。
server computeは平均158.313 ms、p95 268.155 ms、最大321.920 msだった。
frame intervalは平均158.737 ms、p95 266 ms、最大328 msだった。
BrainAppliedE2Eは38件で平均263.658 ms、p95 398.05 ms、最大547 msだった。
このE2EはBridge送信から脳適用までで、意図翻訳時間と音声入力時間を含まない。
6 Action各3回の適用は18/18で、意図的TCP切断後は停止し自動再開しなかった。
Player例外0、owned PID残留0、peak tree RSS 1001127936 bytes、全体wall 98.235秒だった。
接続先はBrain `127.0.0.1:18766`、Bridge `127.0.0.1:18770/18771`である。
backendはMALECNS、ready=false、Startup READYは1234 ms、source hashは`e58b5c612935db1cb856cfe0566ef3364e48c266f3bf347d8083f8222bcebe99`である。

今回測定した性能指標ではp95 step <=250 msが未達である（同居実測268.155 ms）。
observed max <=500 msとE2E p95 <=500 msはこの試験内で達成した。
computeおよびgapの750 ms停止条件はこのtrialで発生しなかった。
ただし、これらは今回の98秒試験内の結果であり、将来の最悪値を保証しない。
moving Actionの変位は3e-7 m未満で、実歩行達成とは扱わない。
マイク入力、実発話、15分連続、Mac接続、指定版でのUnity buildは未試験である。
したがって今回の成功はtransport/runtime gateの成功であり、Unity gameplay acceptanceではない。

## 次の判定

残る性能課題は同居負荷でのp95 step <=250 msと15分連続運転の確認である。
Mac接続、マイク・実発話、新規Unity build、実歩行品質は別の未検証項目である。
継続試験ではstep、frameAge、stale、protocol、E2Eを別々に保存する。
数値一致、直接性能、TCP、Unity、物理挙動を混ぜて一つの合格値にしない。
compiled kernelの168窓結果と98秒の実機結果は今回の採用根拠であり、全入力や長時間運転の保証ではない。

## 再実行コマンド

Flylingualルートから、固定依存を導入済みのWindows環境で実行した。

```powershell
artifacts/windows-malecns/.venv/Scripts/python.exe tools/test_malecns_compiled.py
artifacts/windows-malecns/.venv/Scripts/python.exe tools/validate_malecns_compiled.py --output artifacts/windows-malecns/compiled/equivalence.json
.venv-bridge/Scripts/python.exe tools/verify_native_player.py --cycles 1 --no-microphone --actions
```

数値比較にはbaseline commitのGit履歴と実graph assetsが必要である。
Native試験には既存Playerと通常の会話サービス接続設定が必要である。

## 原本

- [compiled equivalence](../../artifacts/windows-malecns/compiled/equivalence.json)
- [rest probe](../../artifacts/windows-malecns/compiled-rest-probe/results.json)
- [Native trial summary](../../artifacts/windows-native-conversation/validation-20260913-002239/summary.json)
- [Native performance analysis](../../artifacts/windows-native-conversation/validation-20260913-002239/performance-analysis.json)
- [Native Brain evidence](../../artifacts/windows-native-conversation/validation-20260913-002239/brain-evidence.jsonl)
- [count-buffer validation](./M1-malecns-count-buffer-validation.md)
- [Unity native validation](./Unity-Native-Conversation-Validation.md)
- [runtime requirements](../../Brain/MaleCNS/requirements-runtime.txt)
