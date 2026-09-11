# M1 MaleCNS temporal Live backend — experimental handoff

`ready=false`。Macの6 Action機能gateは通過したが、Windows Replay/Liveと操作遅延の受入確認は未実施。
実装commit: `9cbad4e9358f2d7597d6c358db4c4b3fecfe6dfd`。
MaleCNS connectome上のShiu-compatible LIF実験モデルであり、公式シミュレータや生理学的な運動検証ではない。

## 共有するもの

- `Brain/MaleCNS/*.py`：controller、decoder、serverと既存import依存。
- `Brain/MaleCNS/config/analog_temporal_v1.json`：MaleCNS ID、刺激、readout population、校正。
- `Brain/MaleCNS/config/analog_handoff_manifest.json`：元データ公式URL/SHA-256、実行graphと主要source/config/ReplayのSHA-256。
- `Contracts/fixtures/malecns_game_brain_controller_frames_wire_v1.jsonl`：76 frames、6 Action、ready=falseのREPLAY。
- `Docs/mac/temporal-decoder-checkpoint.md` と `Docs/mac/checkpoints/temporal/`：生時系列、失敗を含む比較、独立seed検証、性能。
- LiveをWindows自身で動かす場合だけ、`artifacts/neuron_checkpoint/` の `body_ids.npy`, `indptr.npy`, `targets.npy`, `weights.npy`。約239 MBのportable numeric arrays。Gitには含めず共有フォルダ等で渡す。

MacのPython環境、dylib、compile cache、Unity Libraryは共有しない。
元のMaleCNS巨大データが必要ならmanifest内の公式URLから同じ版を取得する。
graph再生成スクリプトはMacで検証済みだが、Unix依存が残るためWindowsでの再生成を保証しない。
MacのLiveへ接続するだけならWindows側にgraph/Pythonは不要。

## WindowsローカルLiveの起動候補

以下はPowerShell、リポジトリのParallelルートで実行する。Python 3.10を想定。
Windows実機では未実施なので、成功ログを保存してから利用可否を判断する。

```powershell
py -3.10 -m venv .venv-malecns
.\.venv-malecns\Scripts\python.exe -m pip install -r Brain/MaleCNS/requirements-runtime.txt
.\.venv-malecns\Scripts\python.exe Brain/MaleCNS/verify_analog_assets.py --graph artifacts/neuron_checkpoint
.\.venv-malecns\Scripts\python.exe Brain/MaleCNS/brain_server_analog.py --graph artifacts/neuron_checkpoint --config Brain/MaleCNS/config/analog_temporal_v1.json --host 127.0.0.1 --port 8766 --window-ms 50
```

runtimeはNumPy1.24.3とpsutil7.2.2。Brian2/Cython/MSVCはこのruntime経路には不要。
元データも照合する場合はverifyに `--dataset <download-directory>` を追加する。
検証プログラムを `python -O` で実行しない（assertによる照合を含む）。
サーバーはlocalhostが既定。MacへのLAN接続は信頼できる接続先と公開範囲を明示して別途設定する。今回LAN公開はしていない。

## Unity契約とReplay

既存 `BrainProtocol.cs` のnested `motor.forward` / `motor.turn`、`brainTimeMs` を使用。
`Docs/03_SHARED_CONTRACT.md` とfixtureを参照。Actionから出力符号を強制しない。
既存ReplayMotorSourceのpathに上記fixtureを指定する。Unityコード変更はこの便に含めない。
Replayは脳内3.8秒、既存実装の `performance.stepWallTimeMs` 基準では約29.9秒の再生となる。
これは実測時間を保持したもの。Python形式照合は通過したがUnity JsonUtility読込は未検証。

## 校正・機能証拠

全Action共通EMA100ms、turnのみ左右対称hysteresis ON=.1120717169/OFF=.0560358584 mV。
forward deadzone=.0234514551 mV。reference F=.2937641253/T=.3000467732 mV。
2×2はidentity。config内の旧decoderは比較用で、runtimeはtemporalDecoderを優先する。
weights、threshold、NT、刺激、VNC集合は変更なし。Action切替でbrain/filterをresetしない。
旧FlyWire IDは流用せず、configにMaleCNSの刺激・population IDを列挙。

探索3seedと別の初回EMA検証5seedでは4/5だったため、元の探索seedでhysteresisを固定。
さらに別の20261231～35で5/5、全6 Action、安定期最後200msの符号とSTOP300ms以内を確認。
任意の入力順序・長時間安定性・ゲーム操作感を証明したものではない。

## 性能と残るgate

- 脳内stable onset50～150ms、STOP復帰200～300ms。
- Mac実時間stable onset約0.39～1.25秒、STOP復帰約1.55～2.47秒。即応性の問題は残る。
- TCP localhost30sample: E2E mean788.21/p95 799.03ms、step mean395.38ms。
- 最新Action優先、reconnect、error、単一client、network1/reset0をMacで確認。
- TCP RSS94,224,384 bytes、最終5seed peak116,736,000 bytes。mmap遅延読込のprocess値であり全graph常駐量ではない。
- 25/100ms窓は性能測定のみ。意味の検証とserver起動は50ms限定。

Windows側では76 Replay frame/6 Actionの読込、Live接続、forward/turn、reconnect、stale時停止、エラー表示を実測する。
Windowsの実時間性能と操作感を確認し、過大な遅延が許容できなければ実用decoderとして採用しない。
これらが未検証の間は `ready=false` を維持する。今回はMac側機能検証済みの実験版引渡しである。
