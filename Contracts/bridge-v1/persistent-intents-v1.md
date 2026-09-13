# persistent_intents_v1

2026-09-13。既存`bounded_action_plans_v1`を拡張する。`bridge_state.capabilities`に`persistent_intents_v1`を追加。以下の継続・更新規則は旧契約の「すべて有限」「更新で期限を延長しない」規則に優先する。Brain側の6 Action、BrainFrame、motor、制御権、鮮度判定は変更しない。

## 内部proposal

実Responsesは以下8項目をすべて返す。追加項目禁止。自由な実行コード、神経ID、motor値、経路は受け付けない。

| 項目 | 型・値 |
|---|---|
| kind | action / plan / question / clarify / update |
| action | STOP / FORWARD / TURN_R / TURN_L / FORWARD_R / FORWARD_L / null |
| plan | forward_until_concern / right_then_forward / left_then_forward / nudge_right / nudge_left / null |
| validForMs | 正整数またはnull。整数はmaxActionMs以下 |
| reply | 1000文字以下の文字列。実行成功を断定しない短い解釈 |
| operation | new / continue / modify_conditions |
| executionMode | timed / until_next_command / inherit |
| targetExecutionId | nullまたは現在実行IDの文字列（1〜128文字、空白のみは禁止） |

組合せ規則：

- action：有効Action、plan=null、operation=new、targetExecutionId=null。timedでは整数期間、until_next_commandではnull。STOPはtimedのみ。
- plan：action=null、有効preset、operation=new、targetExecutionId=null。timedでは整数期間、until_next_commandではnull。nudge_right/leftはtimedのみ。
- question/clarify：action=plan=null、operation=new、executionMode=timed、targetExecutionId=null、validForMsは既定の正整数。操作状態は変更しない。
- update：action=plan=null、operation=continueまたはmodify_conditions、targetExecutionIdは解釈時のobserved.activeCommand.executionId。continueはinherit / until_next_command（期間null）、またはtimed（期間整数）。modify_conditionsはinherit・期間nullのみ。

旧5項目kind/action/plan/validForMs/replyは、完全な旧組合せに限りnew/timed/target=nullとして互換検証器が扱う。旧形式からupdate・無期限実行は許可しない。実Responses境界は8項目完全一致を別途検査し、旧形式の出力を拒否する。

例：

```json
{"kind":"action","action":"FORWARD","plan":null,"validForMs":null,"reply":"前に進み続ける指示だね。","operation":"new","executionMode":"until_next_command","targetExecutionId":null}
```

```json
{"kind":"update","action":null,"plan":null,"validForMs":null,"reply":"そのままだね。","operation":"continue","executionMode":"inherit","targetExecutionId":"current-command-id"}
```

これは内部翻訳契約。既存player_text／GPT Live client delegationと、未委任の入力字幕を意味分類する補完経路から使う。control clientが任意proposalを直接投入する新messageはない。

補完は同じResponsesモデルとschemaを使用し、`observed.transcriptCandidate=true`で未完・訂正可能な字幕であることを伝える。文字列一致でActionを決めない。分類だけでは操作revisionや既存動作を変更せず、action／plan／updateの有効な意味判定後に同じ実行経路へ合流する。質問は非操作として消費し、clarifyは追記用に保留する。候補の字幕revision・会話世代・epoch・操作revision・受付鮮度を再検査し、更新は現在executionIdも照合する。受理直前の追記や遅着delegationによる二重実行を認めない。

字幕補完のアプリ内`inputId`はLiveの`delegationId`とは別。診断イベント`transcript_candidate_observed`にinputIdと音声時間範囲、`voice_intent_dispatch`に確定commandIdとinputIdを記録する。Liveから届いた実delegationのIDを捏造しない。補完結果のLive appendは`delegation_id=null`とする。新規分類APIが必要になる場合があるが、動作中の定期的な再解釈・延長は行わない。

## 実行ID・期限・更新

新規実行のexecutionIdはcommandIdに対応する。Planの各stepのBrain requestId、planId、更新発話自身のcommandIdとは区別する。新規操作は現在の一つの実行を置換し、有限操作終了後にも旧実行へ戻らない。

timedの絶対期限は受理時の単調時計＋validForMs。until_next_commandは期限null。inheritは既存modeと絶対期限を保持する。期間上限は有限動作に適用し、受付鮮度のmaxIntentAgeMs（既定8000ms未満）はすべての新規・更新提案に適用する。解釈時間を動作期間から差し引かない。

updateは同じexecutionId、現在step、適用待ち／適用済み時刻を保持し、Action再送やPlan再起動を行わない。continue/timedだけは受理時からの明示期間に期限を置き換え、continue/until_next_commandだけは期限を除去する。nudgeをuntil_next_commandへ更新するとcannot_extend_nudgeで拒否する。modify_conditionsは既存危険監視をORで追加するだけで、期限・段階を変更しない。

Bridgeは翻訳前snapshotの参照IDと更新時の現行IDの両方を照合する。STOP・期限切れ・完了・置換・epoch／会話世代変更後はstale_execution等で拒否し、過去操作を復活させない。受付revisionとepochも検査し、更新の検証と反映はawaitを挟まず行う。

監視条件追加には新鮮で危険のないlocal_safety_observationが必要。欠損・失効・unknown・危険の場合は拒否してinhibit＋STOP。すべてのPlanは引き続き監視対象。単純Actionの監視は明示追加時のみ。既存の監視条件を削除する更新はない。

## stateとイベント

`bridge_state.activeExecution`はnull、または次のフィールドを持つ要求状態：

- executionId、action、plan（単純Actionならnull）、step（0始まり）。
- executionMode（timedまたはuntil_next_command）、monitorHazards（bool）。
- requestId（未送信時null、送信後は上流Brain要求ID）。
- remainingMs（有限期限の残り時間、継続ではnull）。

意図翻訳のobserved.activeCommandも現在有効な要求だけを渡す。executionId/action/plan/step/executionMode/monitorHazards/remainingMsにbrainAppliedを加える。Brain stale時はnull。適用確認は身体の移動完了を意味しない。

更新受理時の`command_result`はstage=execution_updated、commandId（更新発話）、executionId（保持実行）、action、epoch、messageを持つ。これは状態更新であり、Brainへ新しいActionを送信した通知ではない。

ログはexecution_started、execution_updated、execution_endedを追加する。実行ID、Action、preset、step、mode、operation、monitorHazards、reason等の固定項目で追跡する。既存command_submitted／command_applied、plan_started／plan_step_submittedと併用し、更新受理とBrain適用と身体観測を区別する。音声・発話本文を新たに常時記録しない。

## 停止と復旧

通常STOPで保持実行を解除する。Brainの適用未確認は既存stopTimeoutMsで監視し、継続指定でも適用なしを無期限に待たない。監視付き実行の危険・観測失効、Brain stale、切断、切替、操作権喪失、会話停止、緊急停止では既存inhibit経路で実行を破棄する。

Nativeの通常有限期限・Plan完了はSTOP＋待受維持。faultから既存手順で待受へ復旧しても、破棄した指示や未適用の旧提案を再送しない。復旧後の移動には新しい操作指示が必要。質問・通常会話は正常に継続している実行を変更しない。

実装と受入れの区別、動作例、検証項目は[指示の保持](../../Docs/integration/Persistent-Intents.md)を参照する。
