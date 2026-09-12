# Windows実Brainによる平地目標到達試験（2026-09-12）

## 結論

4方向各1回で、前・左は到達と停止保持に成功、右・後は60秒以内の停止保持に失敗。任意位置へ確実に移動できるとはまだ判定しない。後方へは旋回と前進で移動し、後退Actionは使用していない。

## 条件

Windows MaleCNS server 127.0.0.1:18766、各試行で所有server＋単一Unity Playerを起動。実BrainFrame受信後に同じ初期姿勢へreset。物理開始前の初期設定以外に位置・回転の強制変更なし。

目標は開始時の水平前方・左・右・後方へ1.5 Unity単位。Ground colliderを残し、ハエ以外の他colliderを実行時のみ無効化して平地を確保。Tibia/FootPad、摩擦、joint limit、質量、Brain/decoderは変更しない。全脚CPGの適用後に吸着を評価する既存の診断条件。初期CPG位相90°、startup補間OFF。

操作役は現在位置と向きから2秒ごとに既存Actionを選択：距離0.4以下ならSTOP、方位誤差20°超ならTURN_L/R、それ以外FORWARD。送信先は常にWindows実Brain。motorの生成やrequestedActionを用いた物理補正は行わない。

合格は距離0.4以内、freshなSTOP Frameのforward/turn絶対値0.01未満、直近約1秒の3D位置変動0.05以内が揃い、さらに1秒継続。速度はログするが、solver速度の振動だけで停止失敗にしない。制限60秒。試行終了後はSTOPを送り、4秒待ってdisconnectする。

## 結果

|目標|停止保持|終了時間|最終誤差|最接近距離|
|---|---|---:|---:|---:|
|前|成功|32.42秒|0.333|0.165|
|左|成功|48.60秒|0.268|0.180|
|右|失敗|60秒|0.831|0.445|
|後|失敗|60秒|0.509|0.099|

後方は35.42秒で半径0.4内へ入ったが、停止保持に至らず通過した。36.1秒の操作ログでは距離0.222、速度0.793でSTOP、38.12秒には距離0.549となってTURN_Rで修正を再開。右は最接近でも半径0.4の外だった。

通信：全4試行でsequence進行、backend=MALECNS_EXPERIMENTAL、ready=false。10,051物理tickのstale消費0、client/protocol error 0。Player終了コードは全て0（アプリ正常終了と到達合格は別）。PlayerログでException:/error CS該当なし。

この試験は単純な2秒周期の自動操作則によるscreeningであり、人間の最適操作でも到達不能だと証明するものではない。各方向1回だけなので再現率も未確定。到達位置の許容半径0.4も高精度操作の実証ではない。現状は旋回中の並進、応答待ち、STOP後の移動を見込んだ操作が必要。

## 保存と再実行

artifacts/windows-malecns/live-goals/{front,left,right,back}-NONE-0/ にgoal-config.json、goal.csv、goal-result.json、body.csv、live.csv、motor-use.csv、live-wire.jsonl、server/Playerログ、manifest.json。
集計：artifacts/windows-malecns/live-goals/goal-summary.json。

legacyのtrial名はFORWARD_L_90_both_0のままだが、この試験の実Action列はgoal.csvとlive-wire.jsonlに記録した動的指令。方向はgoal-config.jsonを参照する。通常の固定8秒診断summaryは今回の到達判定には使用しない。

専用venvで実行（出力先は新しいものを指定）：

```
python tools/run_live_tibia_diagnostic.py --conditions NONE --goals front left right back --repeats 1 --output <new-output>
python tools/analyze_live_goals.py <new-output>
```

本番反映、Brain変更、commit/pushは行っていない。今回のUnity変更は診断flagでのみ有効。

## GIFスキル

個人スキルC:/Users/tiger/.codex/skills/unity-live-gif/SKILL.mdを作成。Unityの実描画キャプチャ→GIF変換→画像確認→Markdown表示を扱う。scripts/encode_gif.pyは既存出力上書きを拒否し、Pillowで連番PNGを変換する。

公式quick_validate.pyは配置前後とも成功。実キャプチャ75枚から800×600、約8.05秒のGIFを生成し、先頭・中間・末尾を確認。時刻間隔はファイルmtimeによる近似と明示。Brain専用venvには画像ライブラリを追加せず、付属画像処理Pythonを使用。PyYAMLを使う公式検証はuvの隔離環境で実施。
