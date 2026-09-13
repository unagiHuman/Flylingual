# Native Brain 指示と身体移動の検証

2026-09-13。**各ケースの開始物理姿勢を揃えた文字指示試験は 18/18 合格**、`native_actions_motion_pass`。初回の連続試験は落下などで incomplete のまま保存する。正式 root は Flylingual、対象は Windows Native Player → 実 Bridge／Responses → 実 MaleCNS Brain → Unity 身体である。実マイクと連続走行安定性は今回の受入れに含めない。

原因は [WindowsReplayDemo](../../UnityProject/Assets/VisualDemo/WindowsReplayDemo.cs) の Native 用 Update が、同じ GameObject に NativeConversationBody がない場合、毎フレーム motor source を null にしていたこと。[ConversationSessionController](../../UnityProject/Assets/RuntimeIntegration/Conversation/Client/ConversationSessionController.cs) は自身の GameObject に body を追加し、最新 [PlayScreenBuilder](../../UnityProject/Assets/RuntimeIntegration/PlayScreen/Editor/PlayScreenBuilder.cs) も conversation services を demo と別 GameObject に置く。この配置では [NativeConversationBody](../../UnityProject/Assets/RuntimeIntegration/Conversation/NativeConversationBody.cs) が検証済み live source を設定しても解除され、Brain 適用と bodyActive が成立したまま locomotion が STOP 入力を受け得た。

修正は Native 用 Update の毎フレーム解除を除去し、既存 NativeConversationBody に source の設定・解除を委ねるもの。初期停止、明示的な操作有効化、epoch、TCP 切断、0.75 秒 stale、session／instance、有限 motor の確認は維持する。物理パラメータ、歩容、Brain、刺激、decoder、ready=false は変更しない。[PlayScreenView](../../UnityProject/Assets/RuntimeIntegration/PlayScreen/PlayScreenView.cs) は「声で操作中／会話のみ／停止中」と既存 ActionFeedback を表示し、操作中のボタン文言も「声で操作中」にする。過去の案内は「直近の操作案内」と区別する。

会話開始は chat_only で、移動指示を実行しない。「声で操作を有効にする」で control 会話・gpt 所有権・新しい停止確認・明示 resume に進む。Unity の Ready は会話 capability、BrainReady は別の表示値である。BrainReady=false 自体は身体を止める gate ではなく、実験状態の宣言を維持したまま既存の制御条件を満たす必要がある。

従来の 18/18 は `native_actions_transport_pass` であり、文字から Action の適用、frame sequence の到達、bodyActive、切断後の停止を確認する試験だった。実変位や旋回の合否は含まない。[直近の旧証拠](../../artifacts/windows-malecns/fixed-point/native-evidence.json) も `physicalMovementAccepted=false` であり、今回の身体移動の合格根拠に転用しない。

新しい [NativeConversationProbe](../../UnityProject/Assets/RuntimeIntegration/Conversation/NativeConversationProbe.cs) は STOP、FORWARD、TURN_R、TURN_L、FORWARD_R、FORWARD_L を各 3 回、合計 18 Action 測定する。移動の文字指示は 8 秒指定、各 Action の applied／frame 到達後に 3 秒間観測する。8 秒間の完走試験ではない。

初回の足場外への落下を受け、再試験では初期停止・接地後に物理姿勢を保存し、**各ケース前に実 Brain への STOP と適用を確認してから同じ物理姿勢へ戻す**。STOP は motor 両軸の絶対値が 0.01 未満で 0.5 秒継続、接地は 5 脚以上で 1 秒継続を要求し、それぞれ最大 20 秒待つ。診断専用の復元は root 位置・向き、関節位置、速度・力の零化、既存 preset の吸着設定、reflex 状態、CPG 位相、接触保持状態を対象とする。物理パラメータを変更せず、Brain 状態・データ・パラメータ・乱数列はリセットしない。Brain は通常の STOP 刺激停止を通じて継続計算する。この条件は短い個別操作の入力配線検証であり、継続走行・足場の端からの回避・ゲーム攻略の受入れではない。

| 検証対象 | 現行 probe の合格条件・記録 |
| --- | --- |
| 指示と入力配線 | applied、bodyActive、有効な観測 sample、観測中 `MotorSource == demo.live` をすべて満たす |
| 歩容 | STOP 以外で CPG 位相の累積移動が 0.1 rad を超える |
| 前進系 | 水平変位が 0.001 m を超え、FORWARD は開始時の身体前方への投影変位、FORWARD_R／FORWARD_L は各 sample の身体前方への累積投影移動量がそれぞれ 0.001 m を超える |
| 旋回系 | sample 間の thorax yaw 差を累積し、右系は +0.1 度を超え、左系は −0.1 度より小さい |
| 接地・落下 | 観測中の接地 sample が 1 件以上あり、終了位置が初期 root 高さより 0.5 m を超えて下にない。全 sample 接地の要件ではない |
| STOP | 観測末尾 0.5 秒の対象 sample が存在し、全対象 sample で水平速度 0.05 m/s 未満、CurrentMotor の forward／turn の絶対値がともに 0.03 未満 |
| 経路の診断 | Brain motor、CurrentMotor peak／終値、CPG 位相、接地・吸着数、thorax 速度、frame age、session／instance、始終位置を記録 |
| 停止安全性 | 意図的 TCP 切断後に身体・操作が停止し timeScale=0、2 秒間自動再開なし、最後の緊急停止で会話と返信音声bufferも停止 |
| 総合判定 | 18 件すべての身体基準、準備中の source 維持、停止条件を満たし、マイク送信 0、report error なしのとき `native_actions_motion_pass` |

初回実測 `validation-20260913-111826` は **incomplete**。実行先 127.0.0.1:18766、MALECNS_EXPERIMENTAL、ready=false。18 件すべての Action 適用と source 維持を確認し、FORWARD 第 1 回は +Z 方向 3.503 m／水平変位 3.508 m、TURN_R 第 1 回は +7.405 度、TURN_L 第 1 回は −45.550 度、FORWARD_R 第 1 回は +51.495 度だった。一方、FORWARD_L 第 1 回は旋回が逆方向で、第 2 周では足場外へ落下した。経路の解除問題が直って実移動したことと、全操作の受入れ未達を分けて扱う。

初回の切断停止・自動再開なし・最終停止は true、Player exception 0、終了後の所有 process 残存 0、wall 140.672 秒。失敗原本は [Native summary](../../artifacts/windows-native-conversation/validation-20260913-111826/summary.json)、[cycle-1](../../artifacts/windows-native-conversation/validation-20260913-111826/cycle-1.json)、[Player log](../../artifacts/windows-native-conversation/validation-20260913-111826/player-1.log) に保持する。対応する [capture metadata](../../artifacts/native-motion/verified-routing-20260913-1119/capture-metadata.json) と [分析](../../artifacts/native-motion/verified-routing-20260913-1119/native-motion-analysis.json) を参照。この初回は各ケースの姿勢復元を行っておらず、再試験と同じ条件の結果として集計しない。

再試験 `validation-20260913-112925` は **native_actions_motion_pass、18/18 validationPassed**。[Native summary](../../artifacts/windows-native-conversation/validation-20260913-112925/summary.json) と [cycle-1](../../artifacts/windows-native-conversation/validation-20260913-112925/cycle-1.json) が原本。physicsResetCount=18、準備中・全ケース観測中の source 維持=true、sequence=911。切断停止・自動再開なし・最終停止・第 2 操作 client 拒否はすべて true、Player exception=0、終了後の所有 process 残存=[]。wall 187.719 秒、process tree peak RSS 1,173,872,640 bytes。

各行は 3 回の最小～最大。前進判定量は FORWARD が開始方向への投影変位、FORWARD_R／FORWARD_L が局所前方への累積投影移動量。TURN の合格は符号付き旋回であり、その場旋回を保証する値ではない。

| Action（各 3 回合格） | 水平変位 m | 前進判定量 m | 累積 yaw 度 |
| --- | ---: | ---: | ---: |
| STOP | 2.630e-8～7.306e-8 | — | +0.000299～+0.000318 |
| FORWARD | 3.264～3.440 | 3.253～3.439 | −0.794～+9.600 |
| TURN_R | 1.705～1.816 | — | +38.047～+40.626 |
| TURN_L | 1.073～1.367 | — | −67.536～−62.559 |
| FORWARD_R | 1.700～1.882 | 1.592～1.980 | +19.916～+53.629 |
| FORWARD_L | 0.976～1.430 | 1.144～1.537 | −79.938～−61.919 |

実行先は 127.0.0.1:18766、backend=MALECNS_EXPERIMENTAL、dataset=male-cns:v1.0、ready=false。capture は単一 instance `b57d67d3-60d3-446c-addd-a76ea1e2e8af`／session `c108759a-b5c9-4f76-b11e-31bce50f954a` を観測し、sequence は単調増加、非連続 gap なし。source hash は `7551dbf610622af15be53ac8c33846d9be7a687e0455417ed3a7773843939e21`、config hash は `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`、graph hash は `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`。

[capture metadata](../../artifacts/native-motion/controlled-start-20260913-1129/capture-metadata.json) に source／Bridge／Unity source／Player assembly／config／配布 graph の個別 hash、実行コマンドと環境を保存する。capture 側は Python 3.10.12、aiohttp 3.14.3、psutil 7.2.2。この環境記録の NumPy／Numba／llvmlite=null は capture 用 Bridge 環境での未取得値であり、Brain 側の依存不在を意味しない。Brain の固定依存は [requirements-runtime.txt](../../Brain/MaleCNS/requirements-runtime.txt) の NumPy 1.24.3、Numba 0.61.2、llvmlite 0.44.0、psutil 7.2.2。今回の capture には Brain process からの依存バージョン再照会値は含まない。

[集計](../../artifacts/native-motion/controlled-start-20260913-1129/native-motion-analysis.json) の Brain compute は 951 frame、mean 177.508／median 177.518／p95 257.075／max 437.961 ms。Bridge の送信→Brain applied は STOP 準備等も含む 42 件で mean 341.214／median 351.500／p95 484.000／max 562.000 ms。これは文字の入力→Responses 推論→身体完了の総時間ではない。初期を除く frame 到着間隔は 949 件、p95 281／max 453 ms。capture rotation は 8 回、rotation gap=0、parse error=0。原データは [slim Bridge events](../../artifacts/native-motion/controlled-start-20260913-1129/bridge-events-slim.jsonl) に保持する。

close 時に既知の `ClientConnectionResetError` が 1 件あり、エラーなしとは報告しない。release イベントの最終 activeControllerCount=0 と process 残存なしを確認済み。親の終了監査では 18766／18770／18771 がすべて解放され、Editor は playing=false、compiling=false、正式 scene、dirty=false。親担当は [FORWARD の PNG](../../artifacts/windows-native-conversation/validation-20260913-112925/motion-FORWARD.png) と [左旋回の PNG](../../artifacts/windows-native-conversation/validation-20260913-112925/motion-TURN_L.png) を視覚確認した。実動作の判定根拠は上記の時系列数値で、GIF／動画は作成していない。

[終了後監査](../../artifacts/native-motion/controlled-start-20260913-1129/post-trial-audit.json) は capturedFilesChangedSinceTrial=[]、Brain stateResetCounts=[0]、networkRebuildCounts=[1] を記録する。物理姿勢の 18 回復元と Brain 状態リセットは別である。

実マイクはユーザーが発話できないため未実施。今回の文字指示は `SendPlayerText` から Responses へ入り、Live のマイク入力・音声認識・client delegation を通らない。音声 Action の実装配線は存在するが、この試験で音声操作を受入済みとはしない。音声の受入れには別途、実発話から `voice_intent_dispatch`、`intent_classified(source=voice)`、Brain applied、Unity 身体観測までの照合が必要である。

通常起動では Ready 後に `EnableVoiceActions` を一度だけ自動実行し、fresh STOP／`resume` gate 後に音声操作を開始する仕様へ更新した。実マイクによる起動時自動開始と音声 Action の検証は現在実施中で、結果はまだ確定していない。明示停止・期限切れ・fault 後の自動再開は行わない。`-flyConversationChatOnly` は会話のみを明示する互換起動である。
