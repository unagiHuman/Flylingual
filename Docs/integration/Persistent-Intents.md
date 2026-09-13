# 指示の保持・継続・条件追加

2026-09-13。ユーザー合意に基づく実装仕様。既存の[大まかな移動指示](Bounded-Action-Plans.md)に、現在の実行状態と終了条件を追加する。ソース上の実装と実API・音声・身体の受入れ結果は別に扱う。

## 操作の意味

| プレイヤーの発話 | 解釈と保持する内容 |
|---|---|
| 次の指示があるまでずっと前に進んで | 新しいFORWARDを停止・次の操作指示まで継続 |
| 少し右を向いて、そのまま進み続けて | right_then_forward。短い右旋回を一度行い、前進段階を継続 |
| もう少し右 | 新しい有限nudge_rightに置換。完了後に以前の前進を再開しない |
| 8秒間前に進んで | 新しい有限FORWARDに置換。受理から8秒で終了 |
| そのまま／そのまま進んで | 現在の段階・絶対期限・監視条件を保持。期限延長も再旋回もしない |
| そのまま、次の指示まで進んで | 現在の段階と監視条件を保持し、終了条件を継続に変更 |
| そのままあと8秒 | 現在の段階と監視条件を保持し、更新受理から8秒の期限に変更 |
| 違和感があったら止まって | 現在の操作に既存の局所危険監視を追加。段階と期限を保持 |
| 止まって | 保持した操作を解除し通常STOP。前の操作へ戻らない |
| 右は危ない？／右がいいかな？ | 質問。現在の操作を変更しない |

時間・継続の指定がない新しい操作は既存の有限動作。明示的な継続意思はResponsesで解釈し、キーワード一致による操作fallbackは作らない。丁寧な依頼、方向の大まかな表現、言い直しは既存解釈を維持する。「右、いや左」は最後の明確な方向を採用する。

方向や動作の省略は、Bridgeが渡す現在有効な`observed.activeCommand`からだけ補う。STOP済み、終了済み、期限切れ、旧世代、操作権失効の実行は文脈に渡さず、「そのまま」で復活させない。「砂糖まで」「安全な方へ」は局所安全フラグだけでは経路を決められず、確認が必要。話すのをやめる依頼は身体のSTOPと区別する。

## 保持する実行状態

Bridgeは同時に一つの`active_execution`を保持する。実行ID、現在Action、plan名、step、終了mode、単調時計の絶対期限（継続ならnull）、危険監視有無、Brain要求ID、epoch、会話世代を分ける。実行IDは新規操作のcommandId。Planの段階ごとのBrain要求IDと実行IDは別である。

`operation=new`は置換、`continue`と`modify_conditions`は同じ実行IDへの更新。更新でBrain Actionを再送したり、Plan taskを再開始したりしない。実行中の短い旋回の適用時刻も保持する。これにより前進段階で「そのまま」と言っても旋回段階には戻らない。

`executionMode=timed`は正整数の`validForMs`で期限を指定する。既定4000ms・最大8000ms（端末設定が短ければその範囲）は有限動作に適用する。`until_next_command`では`validForMs=null`、動作期限もnullとする。`inherit`は更新専用で、既存modeと期限を保持する。nudgeとSTOPの無期限化は認めない。nudgeは期限を変更しても短い旋回完了で終了する。

すべてのPlanは既存の危険監視付き。単純Actionには既定で監視を追加せず、条件追加の発話が受理されたときだけ有効にする。条件追加は既存5種の観測だけを使い、既存条件の削除や未知条件の追加は行わない。監視の追加時点で観測欠損・失効・危険なら追加を拒否して停止・抑止する。

## 受付・競合・停止

指示の受付鮮度と動作期限を分離する。Responses解釈開始から`maxIntentAgeMs`（既定8000ms）未満、現在epoch、最新intent revisionを確認し、置換待ちの後にも再検査する。解釈時間を動作時間から差し引かない。新規操作がまだ解釈中なら旧操作は従来どおり実行でき、受理した時点で置換する。

更新は解釈時の`activeCommand.executionId`を`targetExecutionId`として返す。Bridgeは解釈時の参照IDと一致すること、および更新直前にも同じ実行が有効であることを検査する。検査と更新の間にはawaitを置かない。解釈中にSTOP・終了・別操作・世代変更が入った場合は旧実行への更新を拒否する。質問や確認応答は現在の操作を置換しない。

GPT LiveにもAction・計画段階・終了mode・監視条件とBrain適用の有無をthinkingで通知する。状態が変わった時だけ通知し、起動直後の空状態や、残り秒数・sequenceの変化だけでは送らない。実行IDはBackend内で照合する。通知は新しい操作指示でも身体移動の証拠でもなく、自動継続要求を発生させない。通常経路では「そのまま」など短い発話も、同じ操作が実行中であっても新たなclient delegationを必要とする。Live が delegation を出さず timed transcript fragment だけを返した場合に限り、Bridge は 1 秒 batch の transcript candidate を同じ Responses モデルと persistent 8項目 schema で意味分類できる。これはキーワード fallback でも新モデル／新サービスでもないが、未委任会話に追加の分類 API 呼出しを発生させる。

音声Actionの結果は「送信した」で止めず、BrainFrameで適用を確認した時点で元delegation IDへ返す。Planも各段階の適用を同じ元IDへ返し、残る計画実行はbackendが管理すると伝える。結果通知は一度だけとし、世代変更・新しい要求・抑止後の旧通知は送らない。Brain readerは音声通信を待たない。更新は再刺激なしで完了したことを返す。いずれも身体移動や静止を確認したという報告にはしない。

### 未委任 transcript の補完

1 秒 batch は発話終端や動作根拠ではない。質問／clarify は旧実行を cancel せず、質問は consume、clarify は保留する。新しい transcript delta は投機分類だけを cancel でき、既存の実行は止めない。候補は maxIntentAge、claim、delta、epoch、generation、revision、freshness、current execution を受理前と受理直前に再検査し、既存実行経路へ `prepared proposal` として一度だけ渡す。実 delegation と競合すれば投機結果を破棄し、投機後に遅れて来た delegation を再実行しない。1,500 ms gap は放棄文脈の容量管理だけであり、動作の根拠ではない。2,000 characters または 160 fragments を超えた入力は suffix を実行しない。元 delegation がない補完結果は Live へ delegation ID null で通知する。

Brain stale、操作権や接続の喪失、会話停止、切替、緊急停止、危険監視対象の危険・観測失効では既存inhibit＋STOPに従い、保持指示を破棄する。継続操作もBrain適用なしを無期限に待たず、既存`stopTimeoutMs`で適用待ちを監視する。Planの短い旋回はBrain適用を確認してから500msを測り、次段階の直前にも安全・世代・接続を確認する。

Native音声controlの正常な有限期限・計画完了は通常STOPで待受を維持する。faultから復旧する場合は既存Native手順（新しい音声session・fresh STOP・resume）で待受へ戻り、破棄した指示は再開しない。明示的な緊急停止・mute・会話終了等は既存のユーザー指定を優先する。上流Brain TCPの物理断からの自動復旧は保証しない。

Action→既存神経刺激→MaleCNS→raw神経出力→既存decoder→motor→Unity身体の経路を維持する。継続のためのGPT再問い合わせ、Brain reset、直接motor生成、身体速度の強制設定は追加しない。保持指示は要求状態であり、歩行の継続や即時静止の証拠ではない。

Live delegation の原則は [React to transcript fragments](https://developers.openai.com/api/docs/guides/live-delegation) と [Live conversations](https://developers.openai.com/api/docs/guides/live-conversations) を参照する。

## 通信と検証

[persistent_intents_v1契約](../../Contracts/bridge-v1/persistent-intents-v1.md)に内部8項目schema、state、ログを定義する。既存5項目の有限proposalは互換検証用に受け付けるが、実Responsesの出力は8項目必須。control WebSocketに任意のPlanや更新を直接実行する新messageは追加しない。

実装対象は`Runtime/Bridge/conversation.py`、`conversation_prompts.py`、`action_plans.py`、`control.py`、`server.py`。`tools/verify_persistent_intents.py` の 29 例、明示repeat上限3、自動retryなし。原文は合成例だけを保存し、source hash・モデル・処理時間・分類一致・受付鮮度を記録する。Brain／音声／Unity動作の代替にはしない。

受入れでは、有限期限を超える60秒以上の継続と実身体移動、途中STOP、次操作への置換、「そのまま」で再旋回しないこと、条件追加で期限が延びないこと、質問による非操作、停止後の遅延応答による再始動防止、危険・観測失効・接続障害で旧指示を破棄することを分けて確認する。

実測では handoff-02 の fixture input が client delegation と transcript semantic 補完を混在して通過した。ただし実 Responses の synthetic classification-02 は 29 件中 28 件一致で、nudge の無期限化を提案する 1 件の不一致を残した。実行側は nudge の無期限化を拒否するが、分類の不一致を合格に読み替えない。人間マイクと 60 秒 full persistent の補完経路は未受入れである。

本書の仕様と受入れ結果は分けて扱う。実 Responses 分類、合成音声、Windows実Brain／Unity身体、マイク、操作感はそれぞれの確定証拠が必要である。受入れでは、動けなくなる、停止できない、次の操作を受け付けないといった主要プレイ経路を優先する。条件更新などの厳密 gate の未達や分類の軽微な不一致は残課題として記録し、主要経路に支障がない限りリリース停止の根拠にはしない。既存の有限Plan分類実績や実行側の拒否を継続操作の成功実績に読み替えない。