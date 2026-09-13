# bounded_action_plans_v1

Backend実装、Unity producer／実API／Windows実機の受入れは未完了。
`bridge_state.capabilities`に`bounded_action_plans_v1`を追加。
Brain側の6 ActionとBrainFrameは変更しない。

## 内部の意図proposal

既存Responsesの厳密schemaに `kind=plan` とnullableな `plan` を追加。
全proposalはkind/action/plan/validForMs/replyを持つ。

- kind=action：既存6 Action、plan=null。
- kind=plan：action=null、planはforward_until_concern/right_then_forward/left_then_forward/nudge_right/nudge_left。
- kind=question/clarify：action=null、plan=null。
- validForMsは整数、0超、既存maxActionMs以下。未知fieldと不正な組合せは拒否。

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

ログ：plan_started、plan_step_submitted、plan_stopped、既存output_inhibited／command_submitted／command_applied。
本文・PCM・自由な推論・センサーsnapshotは新たに保存しない。
plan_startedとintent_classifiedのplan値はallowlistのpreset名のみ。

期限・危険でSTOP＋既存出力抑止し、自動resumeしない。
実行と制限は[限定行動計画](../../Docs/integration/Bounded-Action-Plans.md)を参照。
