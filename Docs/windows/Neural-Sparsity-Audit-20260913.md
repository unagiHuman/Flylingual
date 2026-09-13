# 発火が2点に見える理由の調査

現在の前進入力はbody10045/10056の2細胞を直接刺激する。短い可視化試験でこの2点だけを観測したことを、全CNSが常に2細胞しか発火しないという意味にはできない。一方、全細胞を計測しても前進時の下流発火は少なく、生理学的に妥当な脳エミュレーションが検証済みとは言えない。

## 現行Windowsモデルの直接計測

[実行コード](../../artifacts/neural-visual/full-graph-audit-01/audit.py)、[全結果・hash](../../artifacts/neural-visual/full-graph-audit-01/report.json)。実行コマンド:

```powershell
artifacts/windows-malecns/.venv/Scripts/python.exe artifacts/neural-visual/full-graph-audit-01/audit.py
```

本番のMaleCNSAnalogControllerと実graphを直接実行し、返却される全細胞countを読み取った。TCP/Unity/APIを含むE2E試験ではない。重み・閾値・刺激・decoderは変更していない。seed20270101、dt0.1ms、window50ms、N166700、effective CSR entries19670694、atlas24000。初期化1回、状態リセット0。backend MALECNS_EXPERIMENTAL、ready=false。graph4ファイルのSHA256は既存handoff manifestと一致。

初期baseline100msの後、以下を連続実行。時間は脳内時間で、実時間ではない。

| 区間 | 時間 | 発火した細胞 | 総発火回数 | 全入力集合22細胞以外の発火細胞 |
|---|---:|---:|---:|---:|
| STOP | 100ms | 0 | 0 | 0 |
| FORWARD | 8000ms | 9 | 1486 | 7 |
| STOP | 500ms | 0 | 0 | 0 |
| TURN_R | 1000ms | 29 | 1332 | 19 |
| STOP | 500ms | 2 | 2 | 2 |

前進時は10045が748回、10056が719回。残り7細胞は合計19回であり、直接刺激2細胞が全発火の98.7%を占める。発火した9細胞のうちatlasに含まれるのは5細胞。短い旧可視化試験と同じ刺激履歴を再生した結果ではない。

前進中の窓末観測では6726細胞に静止電位から1e-9mVを超える変化があり、膜電位応答まで2細胞に限定されているわけではない。これは窓末の標本による集合で、全tickの最大電位や生理的な有意性の判定ではない。発火count自体は全tickを含む。

202窓、壁時計28.888秒、終了時RSS98836480 bytes（peakではない）。Python3.10.12、NumPy1.24.3、Numba0.61.2。1seedの限定診断であり、広い入力条件や生体の再現性を保証しない。

## 原因と検証範囲

- 全結合は`count × sign × 0.275 × 0.1 mV`。0.1倍は旧モデルの持続過活動を抑えるために選んだ実験値で、現行exact-linearモデルの生理的校正を確認できていない。[旧選定](../mac/M5-M7-report.md)、[現行モデルへの引き継ぎ](../mac/neuron-shiu-checkpoint.md)。低活動の有力要因だが、今回gain比較はしていない。
- 背景入力なし、静止−52mV、発火閾値−45mV。ACh/GABA以外を動的結合から除外する探索用NT policyである。全構造結合を生理的に再現している状態ではない。
- 前進は下流VNC集団の平均膜電位変化をゲーム用motorへ変換する。以前の校正でもVNC発火0で前進値を得ていた。[既存前進検証](../mac/forward-readout-checkpoint.md)。身体が動くことはVNCの発火や生体の歩行回路の再現を証明しない。
- 下流発火を今回実測したため、全シナプス伝達が停止しているとは考えにくい。既存の[371細胞の伝達診断](../mac/subthreshold-diagnosis.md)も伝達は確認したが発火は閾下だった。
- [固定点最適化の408窓bit一致](M1-malecns-fixed-point-validation.md)は変更前の数値を保った証拠であり、変更前モデルの生理的妥当性の証明ではない。

次は、現行モデル上の結合スケールと入力条件の妥当性を再検証し、下流への伝播と刺激停止後の収束の両方で判断する。今回、本番設定を増幅して発火点を増やす変更はしていない。
