# 脳表示の斜め視点

2026-09-13。`NeuralVisualizationPanel` の初期姿勢をX=-18度、Y=35度に変更した。回転を `ApplyView` に集約し、実行時に生成する通常Playerの点群にも、最初のドラッグを待たず初期姿勢を適用する。専用カメラを透視投影とし、距離4、画角 `2 * atan(zoom / 4)` で従来の中心面の表示サイズを保ちながら遠近感を付ける。回転とズーム、脳の拡大表示／全CNS表示は維持する。

変更は表示用Transformと専用カメラだけ。実発火の橙色、正の膜電位変化のシアン、負の変化の紫、神経データ・シミュレーション・身体制御は変更していない。初期角度の問題は、以前のruntime生成時に回転値をTransformへ適用していなかったことにも起因する。

対象Editor（Unity 6000.5.9f1、Pipeline port 7800）でコンパイル成功を確認し、`NeuralVisualizationBuilder.ExportStaticPreview()` で実際のatlas座標を描画した。[全CNS](../../artifacts/neural-visualization/static-anatomy.png)、[脳の拡大](../../artifacts/neural-visualization/static-brain-focus.png)を確認済み。これは静的な解剖表示であり、発火・実Brain接続・ゲーム動作の試験ではない。全CNSは画面内に収まり、脳の拡大では下方のCNSが表示範囲外になる既存の表示方針を維持する。

その後のPlayerビルド前に、別の新規ソース `BlindSugarRunExplorationMap.cs:43` が未定義の `BlindSugarRunMinimapView` を参照するCS0246が発生した。現時点では通常exeの再ビルドと実Player確認は未完了。該当する地図実装は変更せず、他セッションへの連絡も行っていない。エラー解消後の通常Player再ビルドが残る。commit/pushなし。
