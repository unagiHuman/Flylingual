# Native Brain 指示と身体移動の検証

現在の起動時音声操作・停止後の待受継続は、後半の「ゲーム起動中の継続音声操作」を参照。前半は修正前を含む試験履歴であり、当時のchat_only起動や再有効化要件を現行仕様として扱わない。

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

上記11:29の試験時点では実マイクはユーザーが発話できず未実施。文字指示は `SendPlayerText` から Responses へ入り、Live のマイク入力・音声認識・client delegation を通らない。上記18件合格を音声操作の受入れとして扱わない。後続の実マイク試験は以下に分けて記録する。

通常起動では Ready 後に `EnableVoiceActions` を一度だけ自動実行し、fresh STOP／`resume` gate 後に音声操作を開始する仕様へ更新した。明示停止・期限切れ・fault 後の自動再開は行わない。`-flyConversationChatOnly` は会話のみを明示する互換起動である。

## 2026-09-13 起動時音声操作と実マイク

ユーザーの実行ログでは `chat_only` のため身体を操作できなかった。ユーザーの「起動時から音声で操作できる」という指定に従い、通常起動で既存のSTOP／resume確認を自動実行する。新しいLive接続で旧接続のtranscript時刻とdelegation IDを持ち越す別の不具合も修正した。同一接続内の旧epoch無効化は保持する。接続切替・旧音声破棄等のネットワークなし回帰12件は合格したが、実音声の合格根拠には使わない。

起動時自動化の[文字試験](../../artifacts/windows-native-conversation/validation-20260913-114922/cycle-1.json)は `automaticVoiceControl=true`、最初のSTOP／FORWARD／TURN_R／TURN_L／FORWARD_Rの5件で身体判定成功、その後期限切れで **incomplete**。FORWARD_R適用から期限切れまで3.750秒で、3秒観測後の次STOPが間に合わなかった。直前frame age47msでstaleではない。[capture](../../artifacts/native-motion/automatic-voice-start-20260913-1150/capture-metadata.json)には重複収録とparse error1があり、完全一致重複除去後371frame、compute最大497.777ms。8秒指定のうち翻訳時間の控除が何msかは当該ログに記録されていない。

実マイクのOpenAI GPT Live／Responsesへの送信はユーザーの明示承認後に実施した。[実行・hash・終了記録](../../artifacts/native-motion/real-microphone-20260913-1153/capture-metadata.json)、[受動身体観測](../../artifacts/native-motion/real-microphone-20260913-1153/native-voice-observation.jsonl)、[集計](../../artifacts/native-motion/real-microphone-20260913-1153/voice-validation-analysis.json)が原本。実行は `.venv-bridge/Scripts/python.exe artifacts/native-motion/run_manual_voice_capture.py artifacts/native-motion/real-microphone-20260913-1153`。マイクを有効にした正式Playerへテキスト・合成音声・固定motorを注入せず、0.2秒間隔で受動観測した。JSONLは本文・音声を保存せず数値カウンタを保存する。別のPNGには画面の字幕が含まれる。

初回は `voice_intent_dispatch` → `intent_classified(source=voice, FORWARD)` → request3／sequence170適用 → 実身体前進を照合できた。適用後の有効観測29件すべてでBodyActive／sourceEqualsLive=true、Z変位+4.161766m、CurrentMotor最大0.842923、最大frame age166.304ms。ユーザーも「発話した。ハエが動いた」と確認した。delegation dispatchから分類1,921ms、Brain適用まで追加204ms、計2,125ms。発話開始・音声認識時間を含むE2Eではない。

同じPlayerで手動再有効化後、2回目の音声FORWARD request10／sequence786も適用された。有効観測23件すべてsource維持、水平位置変化はdx=-0.279635m／dz=-0.010332mで、初回の前進距離と同等とはしない。初回・2回目とも停止原因は期限切れで、音声STOPの適用は0件。ユーザーの停止の目視確認と、音声STOPの実適用を区別する。期限切れ後の音声TURN_R／TURN_Lは分類されたが適用されず、操作には明示的な再有効化が必要だった。

全期間1116frame、sequence3～1118欠番なし、compute mean144.641／p95213.623／max406.884ms（p95はfloor(.95*(n-1))）、到着間隔最大422ms、process tree peak RSS1,156,784,128 bytes。MALECNS_EXPERIMENTAL／LIVE／ready=false、Brain reset0／rebuild1。source／config／graph hashは上記11:29試験と同じ。Player exception0、終了時controller数0、所有process残存なし、18766／18770／18771解放を確認した。終了時の既知のbackground_failed 1件は残る。停止後に保持されたmotor／速度の表示値を継続移動の根拠にしない。

### 停止語の明確化と追加試験

controlモードの指示文で単独の「止まって」「止まれ」「ストップ」をハエのSTOPとして明示し、「話すのをやめて」の発話停止や否定文と区別した。新しいモデル・APIや文字列一致の自動操作は追加していない。Live delegation／Responses／既存Action／Brain経路を維持する。[公式client delegation資料](https://developers.openai.com/api/docs/guides/live-delegation)に従い、transcript断片だけで操作成功とは扱わない。

追加の[実マイク記録](../../artifacts/native-motion/real-microphone-stop-20260913-1201/capture-metadata.json)と[停止集計](../../artifacts/native-motion/real-microphone-stop-20260913-1201/stop-validation-summary.json)では、voice STOPの分類1件まで確認できたが、分類時点で既に期限切れ後のepoch6であり、STOP submitted／appliedは0件。FORWARDは3件送信、期限切れ3件。**音声による身体停止は未受入れ**。単独STOPの字幕認識、委譲、期限内適用の追加確認が残る。ユーザーが目視した停止を、この因果の証明に置き換えない。

追加試験1292frame、compute mean124.978／p95182.464／max265.707ms、peak RSS1,157,488,640 bytes。完全一致重複0、parse error0、所有process残存なし、ポート解放確認済み。command ID、hash、依存情報、原本SHA256は上記記録を参照する。12件のネットワークなし回帰は追加変更後も合格した。会話本文を保存していないため、未転写と未委譲の区別は今回のカウンタだけでは確定しない。

## ゲーム起動中の継続音声操作（2026-09-13）

ユーザーの「つねにマイクから指示を受け、ゲーム起動中ずっと身体が反応できる状態を維持する」という指定を反映した。Native音声controlの通常TTLではSTOPを1回送信するだけにし、epoch／voice session／motor TCP／新しい指示の処理を維持する。次のActionにボタン再操作は不要。移動の期限は維持し、STOPには移動継続期間を課さず、意図処理の8秒の鮮度制限とepoch・重複・所有権判定を適用する。

Unity側の一時的な身体TCP・制御WS・Live接続不良は古い出力を停止し、fresh STOP／新Live／resumeで待受へ自動復旧する。WebSocket接続試行は10秒、状態通知の無応答は3秒で切り上げる。マイクの同名デバイスの一時的な収録失敗は2秒後に再取得を試す。明示した会話終了・緊急停止・ミュートを自動で上書きしない。上流Brainサービス終了／Bridge→Brain TCPの再接続や別名マイクへの自動切替はこの変更の対象外。

最初の[継続試験](../../artifacts/windows-native-conversation/validation-20260913-121702/cycle-1.json)ではTTL3回の待受継続、身体TCP切断後のSTOP状態での自動復旧、最後の明示緊急停止後の無復旧は成功。一方、6動作各3回の途中で準備STOPが `invalid_command_duration` となり、全体はincomplete（先頭3件成功、次ケース準備失敗）。[拒否原本](../../artifacts/native-motion/continuous-voice-20260913-1216/rejected-stop-evidence.json)を保持した。この失敗を受けてSTOPの期間判定を上記の鮮度制限に修正し、移動指示の期間控除は変更していない。ネットワークなし回帰27件が合格した。実Brainでの再試験は別runに保存する。

修正後の[再試験](../../artifacts/windows-native-conversation/validation-20260913-122335/cycle-1.json)は **18/18合格、native_actions_motion_pass**。通常期限切れを3回またいでも同じepoch／Brain sessionで待受を維持し、期限切れからSTOP適用まで203／281／234ms、その後の新しい移動指示も再有効化なしで適用した。意図的な身体TCP切断では停止後5.641秒でLiveへ自動復旧し、古い移動指示は再実行しなかった。明示緊急停止後は自動再開しない。これは実Responses／Windows Brain／Unity身体への文字指示試験で、マイク送信0。各ケースの物理姿勢復元21回（期限切れ3＋動作18）を含み、連続走行の品質を保証する試験ではない。

[実行とhash](../../artifacts/native-motion/continuous-voice-stopfix-20260913-1224/capture-metadata.json)、[独立集計](../../artifacts/native-motion/continuous-voice-stopfix-20260913-1224/continuous-validation-analysis.json)、[終了記録](../../artifacts/windows-native-conversation/validation-20260913-122335/summary.json)を保存。実行は `.venv-bridge/Scripts/python.exe artifacts/native-motion/run_native_motion_capture.py --output artifacts/native-motion/continuous-voice-stopfix-20260913-1224`。127.0.0.1:18766、MALECNS_EXPERIMENTAL／LIVE／ready=false、Brain reset0／rebuild1。source／config／graph hashは11:29試験と同じ。1324frame、sequence2～1325欠番0、compute mean151.640／p95198.344／max353.032ms。Bridge送信→Brain適用53件はmean271.491／p95406／max453msで、音声認識・Responses処理・身体始動は含まない。peak tree RSS1,174,716,416bytes、wall222.25秒、Player例外0、所有process残存0。終了時ClientConnectionResetError1件は保持する。依存版と個別ファイルhashはmetadataを参照。

その後の[実マイク待受試験](../../artifacts/native-motion/continuous-microphone-20260913-1228/capture-metadata.json)は約3分、音声や文字の注入なしで実施した。マイク入力1727chunk、API送信1687chunk、入力transcript／delegation／音声Actionは0件。今回の音声による連続操作やSTOP適用は**未確認**であり、過去のユーザー目視確認や文字試験で置き換えない。音声queueのbackpressure17件を記録。正常終了後の所有process残存0、18766／18770／18771解放を確認した。

[同試験の集計](../../artifacts/native-motion/continuous-microphone-20260913-1228/voice-validation-analysis.json)では、Live開始後172.985秒、身体有効824sampleの全てで実Brain source／マイク収録・送信を維持。一方、117.562秒間で入力1176chunkに対し送信1152chunkとなり、118.703秒後からqueue超過が発生した。音声送信ループが100msの音声期間に送信処理時間を毎回加算していたため、次回期限を「実際の送信開始時刻＋音声期間（既に過ぎている場合は現在時刻）」へ変更した。過去の送信予定を連続実行せず、送信処理時間を通常周期に含める。通常送信コスト・長い送信遅延・event loop遅延・音声カウンタをネットワークなしで検証し、既存回帰と合わせて30件合格。認識0はqueue超過前から続いていたため、認識が無かった理由をこの送信問題に断定しない。

ただし、この第1修正の[中間試験](../../artifacts/native-motion/continuous-microphone-pacing-20260913-1236/pacing-drift-summary.json)でも約111秒で入力1110／送信1098／queue12となり、sleep復帰の微小超過が累積した。backpressure0のまま試験を終了して原本を保持した。第2修正は前の予定時刻＋PCM期間へ追従しつつ、「実送信開始＋PCM期間の90%」と現在時刻を下限にする。これにより小さな復帰遅れを次周期で吸収し、大幅遅延後のまとめ送りを避ける。3msの反復jitterで100ms周期を維持する検証を加え、ネットワークなし回帰31件が合格した。PCM内容・順序・sample rateは変更しない。[公式WebSocket資料](https://developers.openai.com/api/docs/guides/voice-websockets)の収録sample rateに合わせた連続送信を維持する実装判断である。

第2修正の実マイク試験では3件の音声移動指示を同じepochで適用できたが、159秒時点でqueue7と小さな遅れが残った。最終実装では理想PCM時刻を音声期間だけで加算し続け、実送信開始から90%期間という最短間隔を別変数で保持する。通常のjitterを理想時刻へ戻し、大幅遅延後も最短間隔を守って回復する。20msの周期的oversleepを200回の送信へ混在させても恒久的な遅れが蓄積しないこと、長い停止後に100ms周期へ戻ることを検証し、回帰33件が合格した。

第2修正の[実マイク原本](../../artifacts/native-motion/continuous-microphone-clock-20260913-1240/capture-metadata.json)と[独立集計](../../artifacts/native-motion/continuous-microphone-clock-20260913-1240/voice-validation-analysis.json)では、音声FORWARD→期限切れSTOP→音声TURN_L→期限切れSTOP→音声FORWARD→期限切れSTOPの適用を、同じepoch3／Brain sessionで照合した。間のinhibitは0件。移動とSTOP収束を含む観測区間で水平変位2.922m、左旋回−63.863度、水平変位2.596mを記録した（区間定義は集計参照）。dispatch→Brain適用は2188／1891／1860msで、発話開始からのE2Eではない。音声Action3件に対しclarify3件／question1件、音声STOP適用0件。ユーザーが発話した文面や未記録のボタン操作は断定せず、接続・epochの継続と実適用を根拠にする。身体有効827sample全てで実source／収録・送信を維持、fault/error空。1385frame欠番0、compute mean116.620／p95157.110／max316.470ms、ready=false／reset0／rebuild1。peak RSS1,166,540,800bytes、所有process残存0、Player例外0、終了時ClientConnectionResetError1件を保持する。

### 最終版の実マイク継続操作

[最終実行記録](../../artifacts/native-motion/continuous-microphone-final-20260913-1245/capture-metadata.json)は `.venv-bridge/Scripts/python.exe artifacts/native-motion/run_manual_voice_capture.py artifacts/native-motion/continuous-microphone-final-20260913-1245` で実行。正式Player＋Windows実Brain＋実GPT Live／Responsesへ、ユーザーの物理マイクだけを入力した。約3分の中でFORWARD／TURN_R／FORWARD／TURN_L／FORWARDの5件を同epoch3で適用し、それぞれ通常期限切れSTOPへ進んだ。操作の間も音声待受を維持した。分類7件中2件はclarifyで、音声STOPは0件。この試験を、発話認識が常に正しいことや音声STOPそのものの実機確認としては扱わない。

Live pipelineの最後の時点で入力1721chunk／送信1719chunk、queue最大2／backpressure0／lastErrorCodeなし。初期の音声buffer差2chunkを保ち、過去runのような時間に伴う増加は発生しなかった。起動から終了までのsource/data/config/Assembly hashはmetadataに記録し、親の終了後照合でも変更0。peak RSS1,167,433,728bytes、所有process残存0、18766／18770／18771解放を確認した。今回の約3分と単体試験の範囲での確認であり、15分運転・機器抜差し・上流サービス終了復旧の受入れは別に残る。

[最終独立集計](../../artifacts/native-motion/continuous-microphone-final-20260913-1245/voice-validation-analysis.json)で、動作＋期限切れSTOP収束区間の身体運動は、前進2.775m／右旋回+30.837度／前進0.356m／左旋回−53.357度／前進0.871m。短い変位の理由や連続走行品質は断定しない。5回の期限切れからSTOP適用は172／313／218／204／281ms、次の4操作までepoch・session維持、間のinhibit0。身体有効826sample全てでsourceLive／マイク収録・送信を維持し、fault/error空。1268frame、sequence2～1269欠番0、compute mean126.079／p95180.846／max320.673ms、ready=false／reset0／rebuild1。Player例外0。終了時のClientConnectionResetError1件とbrain_transport_errorを保持する。capture内にはcontroller_released／bridge_stoppedが無いため、プロトコル上の正常終了確認は欠測であり、所有process残存0／ポート解放とは区別する。
