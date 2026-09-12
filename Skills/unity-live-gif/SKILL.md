---
name: unity-live-gif
description: Unity EditorまたはUnity Playerで実際に動く様子を連続キャプチャし、再生可能なGIFとして共有する。ゲーム動作の録画依頼に使い、生成画像による動作の再現には使わない。
---

# Unityの実描画をGIFにする

対象プロジェクトのAGENTS.mdと既存録画経路を確認する。実行中のEditor/Playerと、録画のため新たに起動したPlayerを区別して説明する。実描画を記録し、合成した動きを実機検証として提示しない。

FlylingualでWindows Brain接続が指定されている場合は、実Windows Brainへ接続して録画する。ReplayやMacへ暗黙に切り替えない。既存tools/run_live_tibia_diagnostic.pyを読むと、--captureでUnity ScreenCapture.CaptureScreenshotによる連番PNGを取得できる。出力先は毎回新しくする。動かすActionは依頼に合わせ、例の右前進を全用途へ固定しない。

既存のUnityネイティブキャプチャを優先する。新しいビルドが必要な場合はunity-cliスキルに従う。UIから録画する場合は利用可能なcomputer-useスキルの正規APIを使う。録画処理のためゲームの速度や物理パラメータを変更しない。

連番PNGからGIFへ変換するときは[scripts/encode_gif.py](scripts/encode_gif.py)を使用する。Pillowが必要。専用Brain環境にライブラリを追加する代わりに、利用可能ならload_workspace_dependenciesで画像処理用Pythonを取得する。

```
python scripts/encode_gif.py <capture-directory> <new-output.gif>
```

既定の時間間隔は元ファイルmtime差による近似。明示した一定FPSで再生する場合は--fpsを指定し、撮影時刻と異なる速度なら説明する。既存出力は上書きしない。元PNGは保存する。

変換後はGIFのフレーム数・サイズを確認し、元の先頭・中間・末尾フレームをview_imageで確認する。被写体が見えることと実際の姿勢変化を確認する。接続モードの説明はログのbackend/readyに合わせる。

最終応答では短い説明と絶対パスのMarkdown画像でGIFを表示する。例：`![Unityの実行映像](/absolute/path/output.gif)`。外部への公開やpushは録画依頼だけでは行わない。
