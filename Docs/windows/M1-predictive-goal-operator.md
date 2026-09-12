# 遅延・停止距離を考慮するテスト操作役（2026-09-12）

## 結果

Windows実MaleCNS接続で同じ4方向を再試験し、4/4で到達・停止判定に成功。旧操作役の2/4から改善した。ただし各方向1回のscreeningであり、任意位置への到達保証や成功率100%の推定ではない。

|方向|旧方式|新方式|新方式の最終誤差|
|---|---|---|---:|
|前|成功 32.42秒|成功 48.06秒|0.328|
|左|成功 48.60秒|成功 28.10秒|0.156|
|右|未達 60秒|成功 45.00秒|0.399|
|後|停止保持失敗 60秒|成功 50.96秒|0.379|

右は許容半径0.4に対して余裕がほとんどなく、長時間の停止保持や反復成功は未検証。前は遅くなり、全方向で高速化したわけではない。

## 変更内容

操作役だけの診断オプション-diagnosticPredictiveGoalを追加。

- 判断周期を2秒から0.2秒へ変更。Actionが変わった時だけ送信する。
- 約1秒の位置観測から目標へ近づく速度を推定し、速度×停止予測時間を停止距離とする。目標半径0.4にその距離を加えた位置で早めにSTOPを送る。
- yawの差分を平滑化し、角速度×停止予測時間から旋回後の行き過ぎを見積もる。予測角は0～80度に制限し、目標方向の手前でSTOPする。
- STOPのBrainFrameがzero近傍になり、姿勢が落ち着くまで次の刺激を待つ。移動Actionの応答待ちも行う（stale時や目標接近によるSTOPは優先）。
- 停止予測時間は既知の応答を参考に2.5秒から開始し、停止後の観測時間で更新、0.5～6秒に制限。これは保守的な近似であって厳密な制動モデルではない。
- goal.csvへ停止予測時間、停止距離、角速度を追加。

制御経路は位置/向き観測→既存Action→Windows実Brain→BrainFrame→motor→CPG→PhysX。操作役からmotor値や身体姿勢への直接補正はない。

## 共通の試験条件

127.0.0.1:18766、実Windows MaleCNS server、各試行seed20270101、単一Unity接続。通常Tibia/FootPad接触、既存の処理順統一。開始点から各方向1.5 Unity単位の平地目標、60秒制限。

合格基準は旧方式と同じ：半径0.4以内、freshなSTOP応答でforward/turnが0.01未満、直近約1秒の姿勢変動0.05以内を満たした状態がさらに1秒継続。判定後4秒待機の全期間について位置保持を再判定しているわけではない。

旧結果はartifacts/windows-malecns/live-goals。今回はpredictive-goals。操作列が変わるので神経出力も同一ではない。各方向1回、実行時刻も異なる比較であることを保持する。

## 検証と保存

Windowsビルド成功、全4 Player終了コード0。8,606物理tickのstale消費0、client/protocol error 0。全試行sequence進行、backend=MALECNS_EXPERIMENTAL、ready=false。PlayerログのException:/error CS該当なし。

artifacts/windows-malecns/predictive-goals/goal-summary.jsonと各方向のgoal.csv、goal-result.json、live-wire.jsonl、motor-use.csv、body.csv、manifest.jsonを保存。buildログはpredictive-goals-build.log。

再実行は新しい出力先で：

```
python tools/run_live_tibia_diagnostic.py --conditions NONE --goals front left right back --repeats 1 --predictive-goal --output <new-output>
python tools/analyze_live_goals.py <new-output>
```

--predictive-goalなしでは比較用の旧操作則を維持する。

## 変更範囲

UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.csとtools/run_live_tibia_diagnostic.py、および本レポート。SerializeField、Brain、decoder、本番物理設定、通常のプレイヤー入力は変更していない。未commit・未push。
