# Neural Glow 検証記録（2026-09-13）

## 結論

before-01 は実 Brain の `brain_frame` を受動表示し、実発火した 2 細胞に橙色の発光が出ることを確認した。Brain データの欠落ではない。24,000 細胞を小さい UI 領域へ縮小するため、少数細胞の発光は数ピクセルとなり見落としやすい。遮蔽を原因とは断定しない。

この記録は、テキストによる 8 秒前進指示を Responses 経由で送った実 Brain 表示の確認である。人間マイクは試していない。After-01 は PASS し、実発火した 2 細胞の orange glow を画像と RenderTexture で目視確認した。before/after は時刻と発火標本が異なるため、warm pixels の増加を性能改善率として比較しない。

## before-01 の証拠

- 範囲: `real_brain_text_command_neural_render`
- 実 Brain: `127.0.0.1:18766`、`MALECNS_EXPERIMENTAL`／`LIVE`
- 観測・表示細胞数: 24,000
- positive spike samples: 30
- warm pixels 最大: 316
- Player 解像度: 1280×800。神経 UI の表示高さは約 184 px
- movement requested: true、visual error: 空、run status: PASS
- microphone tested: false

原本は [before-01 metadata](../../artifacts/neural-visual/before-01/runner-metadata.json)、発火時の画像は [neural-firing.png](../../artifacts/neural-visual/before-01/neural-firing.png) に保存する。`ready=false` は受信値をそのまま表示しており、発火 payload の有無を置き換えるものではない。

## 視認性の最小改善

After-01 では、`NeuralPointCloud` と shader の既定値を同じ値で次のように調整する。

| 項目 | 旧 | 新 |
|---|---:|---:|
| afterglow | 0.25 s | 0.45 s |
| spike halo scale | 2.4 | 4.0（上限 5） |

発光の起点は positive count のみとする。fresh な count 0 は残光を減衰させ、欠測または stale は表示活動を消去する。データ、count、細胞位置、刺激、数値計算、身体制御は変更しない。二つの renderer を併用する案は採用しない。

## after-01 の結果

- status: PASS、runner wall: 25.437 s、exceptions: 0
- 60 samples 中 positive spike samples: 29、最大 17 spikes／50 ms window
- sequence: 16 → 109、warm pixels 最大: 988
- 有効な既定値: afterglow 0.45 s、spike halo scale 4.0
- cleanup: owned PID は空、ports free: true

原本は [after-01 metadata](../../artifacts/neural-visual/after-01/runner-metadata.json) と [after firing screen](../../artifacts/neural-visual/after-01/firing-screen.png) に保存する。source/config hash、RSS、環境版は metadata 原本を参照する。これは現在の 50 ms 計測窓の aggregate count を描画した確認であり、個々の spike 時刻を描く検証ではない。

## 残る確認

After-01 で発火時の橙色表示は確認済みである。切断・再接続、長時間負荷、人間マイクはこの検証範囲外である。
