# 提出用の小さなゴール補助

2026-09-15更新。ゴール判定の拡張に加え、既知コースへの穏やかな旋回補助と、入口で向きを合わせる間の前進抑制を行う。以下の最新実装は検証中であり、末尾の旧版限定試験とは区別する。

位置は `BlindSugarRunSession.fly.Position`、ゴールは既存の `Volumes/GoalVolume`。移動の接続箇所は `FlyLocomotionController.FixedUpdate` の既存reflex評価後・平滑化前。`FlyDemoSafetyAssist` が既存の神経由来の活動量に比例して旋回成分を補正し、向き合わせ中には前進成分を減衰する。BrainFrameとmotor sourceを書き換えず、物体の座標変更・力の追加・ジャンプは行わない。既存reflexの入力も維持する。

この補助はUnity側のゲーム演出であり、神経反応・学習・食物への感覚入力ではない。成功を神経モデルだけの成果として解釈しない。

## 設定

正式シーン `BlindSugarRunPlay` の `Blind Sugar Run Game Session` にInspector用コンポーネントを配置した。`FlyDemoSafetyAssist.enableDemoSafetyAssist` をOFFにすると旋回補助とゴール判定拡張の両方が無効になり、元の判定へ戻る。

- `BlindSugarRunGoal.clearDistance=0.8`：既存ゴールの水平境界を外側へ0.8拡張。上下の境界は維持。接地・新鮮な実接続・身体安全性が0.2秒続けば、歩行中でもクリアする。OFFでは元の静止・左右安全・1秒条件。
- `nearGoalRadius=3`、`nearGoalMaxAssist=0.45`：3～2で0.10、2～1で0.25、1未満で0.45。
- `noProgressStartTime=8`、`stuckMaxAssist=0.35`：前進要求中の停滞8/15/25秒で0.10/0.20/0.35。ゴールとの距離が0.1縮むとリセット。STOP・旋回要求中は停滞時計を進めない。
- `emergencyStartTime=45`、`hardEmergencyTime=75`：プレイ中の経過45/75秒で0.20/0.45を加える。
- `laneAssist=0.3`、`matchingTurnAssist=0.5`：前進時のコース補助と、明示された旋回方向に一致する補助の基準値。近距離・停滞・経過時間の合算が上回ればそちらを使う。
- `maxTotalAssist=0.65`、`assistChangeSpeed=0.2`：補助の上限と秒当たりの滑らかな変化量。
- `alignBeforeWalkingAngle=35`：進路との角度が35～80度で前進抑制を増やす。旋回中、または現在の向きの前方経路が支持されない場合も補助量に応じて前進を抑える。後退は追加しない。

タイトル・接続異常・ポーズ・Goal/GameOverでは補助しない。有効なFORWARD系またはTURN_L/TURN_R要求、新鮮な実Brain出力、接地と身体安全性、有効なコース観測が必要で、前進・旋回の活動量がともに0.01以下なら補助しない。STOPや要求期限切れを打ち消さず、明示された左右と逆のコース補正を行わない。manualを含めプレイヤーの明示方向を自動案内で置換しない。現在の実装は会話側ActiveExecutionがある場合にだけ働く。

`BlindSugarRunRouteHint` は既知の広い迂回路を使い、本からゴールへ直線で狙わない。WideRouteAの入口を経路点に含め、中心線を外れた場合も支持を確認した次の接続点へ戻す。最大6mの候補区間を足位置・足半径を含む幅で検査し、角を横切る先読みが不支持なら接続点までに留める。旋回は各足とその縁を必要な角度まで掃引して地面支持を確認するため、前方だけの崖検出とその場の旋回可否を分ける。これらは限定的な支持検査であり、転落防止の保証ではない。

経過時間はゲーム開始後だけ計測し、ポーズ・接続待ちでは休止する。Retryのシーン再生成と補助OFFでリセットする。新しい収集目標、スコア、匂い場、Intent Agreement、Anti-Stuck impulseは追加しない。

## 確認の範囲

Editorの最初の起動試験は、タイトル段階で`conversation_settings_timeout`、fresh=falseとなったため終了した。補助はタイトル中に作動しておらず、この結果を移動試験の合格とはしない。

限定Player probeは `-flyConversationProbe -flyDemoAssistProbe -flyConversationNoMicrophone`。実Windows Brainと実会話サービスを使い、通常のテキスト指示で前進・STOPする。開始時の移動、遠距離の補正なし、近距離の旋回補正、OFF、STOP、拡張境界でのクリアを確認する。近距離とクリアは検証時だけゴールtriggerを開始地点付近へ移すfixtureで、ハエやmotorの差し替えはしない。実コース踏破の成功を意味しない。

停滞・45/75秒の閾値はコード確認とし、全コース・物理マイク・長時間プレイは人手での確認に残す。方向補正と判定拡張による救済であり、任意の位置や操作からのクリアを保証するものではない。

最初のPlayer限定試験では移動・補助・STOP・拡張クリアは成立したが、RevealのUIDocumentがGameOverの子になっているためPanelSettings競合のAssertionExceptionが1件出た。正常なクリア表示までの合格とはしない。RevealのUIを同じシーン内の独立したrootへ配置する最小修正を追加した。

## 旧版の限定試験結果（最新補助の合格ではない）

修正版ZIPを展開した実Playerで `demo_assist_limited_pass`。`MALECNS_EXPERIMENTAL`、raw ready=falseをそのまま記録、fresh=true、実Brain motor sourceを維持。開始時の通常前進で水平1.693移動し、遠距離では補正0。近距離の最大補助0.268、最大旋回補正0.207。STOPとOFFでは補正なし、拡張境界でクリアし、Reveal完了とクリア画面の描画を確認した。controller error空、Player例外0、終了コード0、強制cleanupなし、残存所有processなし。

Bridgeログはframe 103件、sequence 4→106、Brain transport failure 0件。終了時の背景送信に既知の`ClientConnectionResetError`が1件残る。実コースをクリアした記録ではない。

成果物：`artifacts/submission-demo-assist-20260915-release/Flylingual-Judge-Windows-submission-demo-assist-20260915-release.zip`

SHA-256：`241c6b4c598eedb7b4dce71be3b2f23e06a48426e6372011af4a6f88b7697233`

Unity 6000.5.9f1 Judge/CloudビルドはSucceeded（終了UTC 2026-09-14 16:41:32）。BuildReportのエラー1件はCLIの5秒待機超過で、コンパイルエラーではない。既存の非推奨API等の警告44件。全2,973ファイルのmanifest/ZIPハッシュ照合に合格し、OpenAIキーの同梱検出0件。

コマンド、選択ソースhash、設定・データhashのmanifest参照、結果JSONと画像は `artifacts/demo-assist-20260915/` に保存。既存作業ツリーからのビルドで、別作業のUI・足音等も含まれる。sceneの新規componentにある空`m_Name`の末尾空白はUnity自身のシリアライズ出力として保持した。

## 最新変更の確認状況

最新版は2026-09-15の実Brain全コース試験でゴール・Reveal完了を確認した。通常の文字指示による経路追従を1回実行し、254.65秒、死亡0、実Brainソースと鮮度を維持、例外0、終了コード0、所有process残り0。マイク入力や人手で感じる自然さの検証ではない。以前の失敗記録は維持する。

終盤の曲がり角で全脚の支持を要求すると停止したため、最終版の旋回判定は掃引区間全体で「4本以上の足が支持され、左右・前後に分散すること」を要求する。前進は身体幅を含む2mの支持検査を使い、広い範囲を見る縁警告だけで止めない。安全性や走破を全条件で保証するものではない。

成果物は `artifacts/submission-natural-assist-final/Flylingual-Judge-Windows-submission-natural-assist-final.zip`。SHA-256: `09887c2078fce3f5437e0bacb39ddc75355c445ac73cc48111874df0c6dac13b`。全2,974収録ファイルのハッシュ照合に合格。証拠は `artifacts/natural-assist-final-test/player/probe.json` と `runner.json`、`player.log`。詳細は[英語表示と経路案内](English-Only-Route-Guidance.md)。
