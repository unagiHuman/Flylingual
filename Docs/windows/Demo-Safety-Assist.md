# 提出用の小さなゴール補助

2026-09-15。ゴール判定の拡張、近距離補助、前進中の進展停滞補助、経過時間による補助だけを追加した。Brain Emulator、GPT Live、入力形式、神経デコーダーは変更しない。

位置は `BlindSugarRunSession.fly.Position`、ゴールは既存の `Volumes/GoalVolume`。移動の接続箇所は `FlyLocomotionController.FixedUpdate` の既存reflex評価後・平滑化前。`FlyDemoSafetyAssist` が旋回成分だけを補正し、前進値はそのまま渡す。BrainFrameとmotor sourceを書き換えず、物体の座標変更・力の追加・ジャンプは行わない。既存reflexの入力も維持する。

この補助はUnity側のゲーム演出であり、神経反応・学習・食物への感覚入力ではない。成功を神経モデルだけの成果として解釈しない。

## 設定

正式シーン `BlindSugarRunPlay` の `Blind Sugar Run Game Session` にInspector用コンポーネントを配置した。`FlyDemoSafetyAssist.enableDemoSafetyAssist` をOFFにすると旋回補助とゴール判定拡張の両方が無効になり、元の判定へ戻る。

- `BlindSugarRunGoal.clearDistance=0.8`：既存ゴールの水平境界を外側へ0.8拡張。上下の境界は維持。接地・新鮮な実接続・身体安全性が0.2秒続けば、歩行中でもクリアする。OFFでは元の静止・左右安全・1秒条件。
- `nearGoalRadius=3`、`nearGoalMaxAssist=0.45`：3～2で0.10、2～1で0.25、1未満で0.45。
- `noProgressStartTime=8`、`stuckMaxAssist=0.35`：前進要求中の停滞8/15/25秒で0.10/0.20/0.35。ゴールとの距離が0.1縮むとリセット。STOP・旋回要求中は停滞時計を進めない。
- `emergencyStartTime=45`、`hardEmergencyTime=75`：プレイ中の経過45/75秒で0.20/0.45を加える。
- `maxTotalAssist=0.65`、`assistChangeSpeed=0.2`：合算上限と秒当たりの滑らかな変化量。

タイトル・接続異常・ポーズ・Goal/GameOverでは補助しない。既存の有効なFORWARD系要求と正の神経前進出力がある場合だけ旋回を補正する。STOPや要求期限切れを補助で打ち消さない。既存の地形観測が危険側を示す場合、その方向へ旋回補助しない。

経過時間はゲーム開始後だけ計測し、ポーズ・接続待ちでは休止する。Retryのシーン再生成と補助OFFでリセットする。新しい収集目標、スコア、匂い場、Intent Agreement、Anti-Stuck impulseは追加しない。

## 確認の範囲

Editorの最初の起動試験は、タイトル段階で`conversation_settings_timeout`、fresh=falseとなったため終了した。補助はタイトル中に作動しておらず、この結果を移動試験の合格とはしない。

限定Player probeは `-flyConversationProbe -flyDemoAssistProbe -flyConversationNoMicrophone`。実Windows Brainと実会話サービスを使い、通常のテキスト指示で前進・STOPする。開始時の移動、遠距離の補正なし、近距離の旋回補正、OFF、STOP、拡張境界でのクリアを確認する。近距離とクリアは検証時だけゴールtriggerを開始地点付近へ移すfixtureで、ハエやmotorの差し替えはしない。実コース踏破の成功を意味しない。

停滞・45/75秒の閾値はコード確認とし、全コース・物理マイク・長時間プレイは人手での確認に残す。方向補正と判定拡張による救済であり、任意の位置や操作からのクリアを保証するものではない。

最初のPlayer限定試験では移動・補助・STOP・拡張クリアは成立したが、RevealのUIDocumentがGameOverの子になっているためPanelSettings競合のAssertionExceptionが1件出た。正常なクリア表示までの合格とはしない。RevealのUIを同じシーン内の独立したrootへ配置する最小修正を追加した。

## 最終結果

修正版ZIPを展開した実Playerで `demo_assist_limited_pass`。`MALECNS_EXPERIMENTAL`、raw ready=falseをそのまま記録、fresh=true、実Brain motor sourceを維持。開始時の通常前進で水平1.693移動し、遠距離では補正0。近距離の最大補助0.268、最大旋回補正0.207。STOPとOFFでは補正なし、拡張境界でクリアし、Reveal完了とクリア画面の描画を確認した。controller error空、Player例外0、終了コード0、強制cleanupなし、残存所有processなし。

Bridgeログはframe 103件、sequence 4→106、Brain transport failure 0件。終了時の背景送信に既知の`ClientConnectionResetError`が1件残る。実コースをクリアした記録ではない。

成果物：`artifacts/submission-demo-assist-20260915-release/Flylingual-Judge-Windows-submission-demo-assist-20260915-release.zip`

SHA-256：`241c6b4c598eedb7b4dce71be3b2f23e06a48426e6372011af4a6f88b7697233`

Unity 6000.5.9f1 Judge/CloudビルドはSucceeded（終了UTC 2026-09-14 16:41:32）。BuildReportのエラー1件はCLIの5秒待機超過で、コンパイルエラーではない。既存の非推奨API等の警告44件。全2,973ファイルのmanifest/ZIPハッシュ照合に合格し、OpenAIキーの同梱検出0件。

コマンド、選択ソースhash、設定・データhashのmanifest参照、結果JSONと画像は `artifacts/demo-assist-20260915/` に保存。既存作業ツリーからのビルドで、別作業のUI・足音等も含まれる。sceneの新規componentにある空`m_Name`の末尾空白はUnity自身のシリアライズ出力として保持した。
