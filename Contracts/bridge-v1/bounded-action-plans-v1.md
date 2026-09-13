# bounded_action_plans_v1

明示継続・現在操作の更新は [persistent_intents_v1](persistent-intents-v1.md) を併用する。
以下の5項目proposalと全体期限は従来の有限操作の契約。新8項目proposalでは継続modeと参照executionIdを明示する。

BackendとUnity地形センサーproducerはソース上で接続済み。Windows実機の音声計画受入れは未完了。
`bridge_state.capabilities`に`bounded_action_plans_v1`を追加。
Brain側の6 ActionとBrainFrameは変更しない。

## 内部の意図proposal

既存Responsesの厳密schemaに `kind=plan` とnullableな `plan` を追加。
全proposalはkind/action/plan/validForMs/replyを持つ。

- kind=action：既存6 Action、plan=null。
- kind=plan：action=null、planはforward_until_concern/right_then_forward/left_then_forward/nudge_right/nudge_left。
- kind=question/clarify：action=null、plan=null。
- validForMsは整数、0超、既存maxActionMs以下。未知fieldと不正な組合せは拒否。
- 指示の受付期限は解釈開始からmaxIntentAgeMs（既定8000ms）未満。旧Planの取消待ち後にも再検査する。Planの実行期限は受付時からvalidForMsとし、解釈時間を差し引かない。複数step全体で一つの期限を共有し、更新で延長しない。

これはBrainへの新Actionではない。control clientからplanの直接実行messageも追加しない。
既存player_text／有効なclient delegationを介して意図翻訳が提案する。

## local_safety_observation

同じ単一control WebSocketから、信頼するUnityセンサーproducerだけが送る。
厳密な10フィールド：

```json
{
  "type": "local_safety_observation",
  "controlEpoch": 7,
  "conversationGeneration": 3,
  "sequence": 1,
  "ageMs": 0,
  "groundPresent": true,
  "leftEdge": "safe",
  "rightEdge": "safe",
  "forwardBlocked": false,
  "bodyUnsafe": false
}
```

controlEpochとconversationGenerationは最新Bridge stateと一致が必要。
sequenceは同じ世代内で単調増加する正の整数、上限2^53。
ageMsはセンサー採取から送信までの有限0〜750ms（異なるPC時計は減算しない）。
受信後はBridge単調時計で経過を加算し750ms以上で失効。古い同一sequenceの再送で鮮度を更新しない。
Unityは送信直前にageMsを更新し、滞留した通知を破棄する。輸送遅延をBridge単独では実証できない。

groundPresent/forwardBlocked/bodyUnsafeはbool。左右edgeはsafe/near/very_near/unknown。
追加key・不正型・不正値は拒否し、稼働中の計画があれば停止する。旧epoch通知は受理しない。
inhibitや会話停止でsnapshotを破棄する。再開時は新しい観測が必要。
chat_onlyからは受信しない。観測自体はBrainのreadyや鮮度を更新しない。

## status/log

`bridge_state.actionPlan`はnull、またはplanId/name/step/requestId。
stepは0始まり、requestIdは未送信時null、送信後はBrain側要求ID。
これは計画状態であり身体の達成状態ではない。

`bridge_state.localSafety`はsource=`unity_local_sensors`、sequence、ageMs（未受信はnull）、
fresh、concern、facts。factsは新鮮な場合だけgroundPresent/leftEdge/rightEdge/forwardBlocked/bodyUnsafe。
未受信／750ms以上経過ではfacts={}。fresh=trueでも危険はあり得る。安全・接続・readyと混同しない。
同じ限定snapshotを意図翻訳へ渡す。activeCommandは現在有効なGPT要求だけで、身体動作の証明ではない。
これらは観測／参考情報であり、新しい操作権やplan直接実行commandではない。

ログ：plan_started、plan_step_submitted、plan_stopped、既存output_inhibited／command_submitted／command_applied。
初回・危険状態変化の受信：local_observation_received（sequence、reason）。
本文・PCM・自由な推論・センサーsnapshotは新たに保存しない。
plan_startedとintent_classifiedのplan値はallowlistのpreset名のみ。

危険ではSTOP＋既存出力抑止。Native音声controlの通常期限／完了は、観測・Brain・接続が正常な場合のみ
STOPを送り待受を維持する（plan_stopped.continuedListening=true）。Legacyは抑止を維持。
どちらも旧計画の自動再開・期限延長はしない。安全停止・切断・送信失敗はfull inhibit。
実行と制限は[限定行動計画](../../Docs/integration/Bounded-Action-Plans.md)を参照。
