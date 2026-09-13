# 膜電位変化の色分け表示

通常Playerを更新し、既存の実測`raw.bodyIds/deltaV`を発光表示する。橙色は実測発火と0.45秒の残光、シアンは基準からの膜電位上昇、紫は低下。膜電位は初期baselineとの差の窓平均であり、瞬時電位や発火イベントではない。現在受信する119細胞だけが膜電位表示の対象。24,000表示点すべての膜電位を受信したとは扱わない。

膜電位表示は既定ON。表示上だけ±0.001mV以下を消灯し、絶対値を`abs(delta)/(abs(delta)+0.02)`で強調する。入力配列・神経計算・motor・発火数は変更しない。2mV超は既存packingの上限で飽和するため、輝度から正確な電位を読み取る用途ではない。膜電位には人工の発火時刻や残光を付けない。実際の発火と残光がある細胞は橙色を優先する。未観測/非有限値/失効時は膜電位発光なし。

起動時の表示を全CNSへ変更し、膜電位観測対象のVNCが画面外に出る問題を解消した。神経カードを拡大し、色付き凡例と膜電位の観測細胞数を表示する。

## 検証

Windowsの現行通常Player、実Brain `127.0.0.1:18766`、backend `MALECNS_EXPERIMENTAL`、mode LIVE、ready=false。既存Bridge/Responses経由で「8秒間前に進んで」を1回送信。マイクは無効。表示用の架空データ、Replay、固定motor、追加Brain接続は使用していない。

```powershell
.venv-bridge/Scripts/python.exe tools/verify_neural_visual.py --output artifacts/neural-visual/voltage-01
```

[原本・hash・環境](../../artifacts/neural-visual/voltage-01/runner-metadata.json)、[観測60標本](../../artifacts/neural-visual/voltage-01/report.json)、[実画面](../../artifacts/neural-visual/voltage-01/voltage-screen.png)、[神経描画](../../artifacts/neural-visual/voltage-01/neural-voltage.png)。

- コンパイル成功、shader messagesなし、現行Console errors0。通常exeビルド成功。safe-compile補助スクリプトは旧uloop設定未導入で利用できず、接続済みUnity CLIで停止中Editorのrefresh/コンパイル完了/エラーを確認した。Console履歴に過去の別バッチエラーはあるが今回の失敗とは扱わない。
- 実測発火あり29標本、正の膜電位変化あり31標本。発火0かつ正の膜電位変化あり2標本。
- RenderTexture上の色画素最大: 橙476、シアン9025。開始前・最後はいずれも0。大きさや明るさの厳密な比較試験ではない。
- 膜電位観測119細胞、前進中の代表標本では上昇78細胞。親が保存画面でシアンと橙色を目視した。
- この前進試験では負の変化・紫色の画素は0。紫の符号分岐はソース・shaderコンパイル確認までで、実Brainの負電位による視認確認は未実施。
- 壁時計26.328秒、peak process-tree RSS1,185,558,528 bytes、Player exception0、残留owned PIDなし、使用port解放済み。新しい実マイク試験や歩行の生理学的検証ではない。

## 変更範囲

NeuralPointCloud C#/shader、NeuralActivityObserverの表示用カウンタ、NeuralVisualizationPanelの初期画角、PlayScreenViewの凡例と配置、PlayScreenProbeとverify_neural_visual.pyの計測を変更した。新しいBrain payloadやモデル設定の変更はない。commit/pushは行っていない。
