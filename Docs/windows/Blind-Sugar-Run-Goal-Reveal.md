# Blind Sugar Run — Goal／Reveal

2026-09-13。ゲーム側の到着判定とFinal Revealを実装。Scene／Prefabの手編集は行っていない。

## ゲーム進行

`BlindSugarRunSession`が`BlindSugarRunGoal`を自動追加する。既存killVolumeと同じ`Volumes`内にある唯一の`GoalVolume`を参照する。Colliderが未設定・無効ならクリアしない。

Goal判定はハエの身体中心をColliderのローカル座標へ変換する。範囲内にいて、次の条件が連続1秒成立した時点でゲームがGoalを確定する。

- Windows実Brainの新鮮なフレームと既存Native Bodyの有効な接続。
- 新鮮な局所センサー、接地、危険姿勢なし、左右端safe、観測overflowなし。
- 線速度0.03以下、角速度0.08以下。
- プレイ中で、timeScaleが正。

退出・動作・接続不良・観測失効・epoch／会話世代変更で計時をやり直す。チェック間隔が0.25秒を超えた場合や時計逆行もリセットする。raw Brain ready=falseをtrueに書き換えない。

Goal確定後はPhysXのゲーム時間を一時停止し、マイク入力を抑える。このpauseはBrainのSTOP適用確認ではない。最終音声用に既存Live／TCPを維持し、8秒後に既存EmergencyStopとBody無効化で終了する。デコード値や身体位置・関節は直接変更しない。

## 表示と台本

通常のBlindステージではゲーム映像をHUD内で隠す。開発用`-blindSugarDeveloperView`指定時だけ開始時から表示する。他のステージの表示は維持する。

Goal後、`BlindSugarRunReveal`が全画面を暗転から表示し、3.5秒かけてステージ全体へカメラを引く。描画範囲の計算にだけ環境boundsを使い、GPTへ全体地図やルートを渡さない。既存カメラのRenderTextureは破棄せず退避し、Reveal用Texture／UIは所有コンポーネントが解放する。

Goal／Revealはゲームが先に確定・開始し、その後でNarratorへ通知する。NarratorはGoalのqueued応答を確認してから、実開始済みRevealの通知を送る。未受理時は最大8秒、同会話内で新sequenceを使って再通知する。Goal再通知をBackendで冪等受理し、セリフの重複を抑える。会話世代・epoch変更で待機通知を破棄する。API応答がゲーム進行を起動することはない。

Reveal終了後に「もう一度」を有効化し、既存Scene再読込と新しい音声接続で再開する。死亡数を増やさず、Goal前のマイクmute設定を復元する。

## 検証と残課題

- Unity 6000.5.9f1のEditor用response fileを使った独立Roslynコンパイル：error 0。ライブEditor compile／Player buildとは区別する。
- `tools/test_blind_goal_stability.cs`：連続1秒、退出／動作相当のinvalid入力、epoch／generation変更、欠測、時計逆行・非finite等、純粋な時間判定28チェック合格。Unity物理／Brainの代替試験ではない。
- `tools/test_blind_run_script.py`：6件合格。GoalのACK再通知、Reveal順序、重複発話の抑制を含む。
- 記録：`artifacts/blind-goal-reveal/goal-tests.log`、`artifacts/blind-run-script-integration/compile-result.json`。

既存Unityプロセスの所有がこの作業と確認できないため、停止・再起動・共有Player再ビルドはしていない。Windows実Brainでの到着、実カメラ描画／フェードの目視、実音声のタイミング、勝利後Retryは未実測。既存exeへの反映にはPlayer再ビルドが必要。終端の8秒上限により遅い音声は打ち切られる場合がある。砂糖検出／分岐観測の追加、全コース完走の受入れは別途必要。
