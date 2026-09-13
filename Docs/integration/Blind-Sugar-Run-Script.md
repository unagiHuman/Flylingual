# Blind Sugar Run — 短い台本と適用範囲

2026-09-13。最新のユーザー提供「Blind Sugar Run — Astra向け実装指示書」を台本の基準とする。
全体をGPTへ読ませる文書ではない。制作側の台本正本は
[blind_run_script.json](../../Runtime/Bridge/blind_run_script.json)。日本語と英語を収録。
共通設計は[Brain/GPT Live正本](../Brain-GPTLive-CrossPlatform-Design.md)を維持する。
以前の詳細設計の「安全地点では長い相談可」より、最新の「原則ひと言、最大短い1文」を優先する。

## 演出ルール

- ハエは一言だけ。説明を連発せず、必要な危険報告・質問への回答・場面の節目だけ話す。
- アドリブは同じ意味の短い言い換えに限定。新しい地形、原因、正解ルートを追加しない。
- 地形はUnityの外付け局所センサーによる情報。MaleCNSが画像を見た、感情を読心したとは言わない。
- 全台本、場面一覧、全体地図、未訪問領域、ルートの長さはGPTへ送らない。
- 「板が右向き」は局所的な向きの観測であり「左へ動け」という指示ではない。プレイヤーが判断する。
- 長短の経路比較は現在の局所観測では証明できないため初版では読ませない。道幅の特徴だけを伝える。
- 「甘い匂い」は嗅覚センサー未実装なので収録しない。砂糖検出は局所の明示的検出が必要。
- 質問はActionなし。NONEを第7のBrain Actionとして送らない。明確な指示だけ既存意図翻訳へ渡す。
- 受付、Brain適用、身体動作、ゴール確定を混同しない。台本処理からActionを発行しない。

## 場面の台本

これは制作側の順序であってGPTが先読みする内容ではない。条件成立時に該当する一行だけを選ぶ。
チュートリアルも一括で読み上げず、ゲーム側が各練習のタイミングで一つずつ通知する。

| 場面／観測 | cue | 日本語の一言 |
|---|---|---|
| Stage開始確認 | intro | ぼくの声で、砂糖を探そう。 |
| 外付けセンサー利用可能 | vision | 外付けの目で、近くがわかるよ。 |
| 周囲質問の練習 | ask | 周りのこと、聞いてね。 |
| 前進練習 | forward_lesson | 「前に進んで」って言ってみて。 |
| 旋回練習 | turn_lesson | 「右向いて」「左向いて」で向きを変えるよ。 |
| STOP練習 | stop_lesson | 止まるのはゆっくりだから、早めにね。 |
| 定規を局所検出 | ruler_ahead | 前に、細い板。 |
| 定規の向きが右 | ruler_right | 板は、少し右向き。 |
| 定規の向きが左 | ruler_left | 板は、少し左向き。 |
| 定規が正面に合った | aligned | 板が、だいたい正面。 |
| 右端が近い | right_edge | 右の端が近い。 |
| 右端が非常に近い | right_edge_urgent | 右、ぎりぎり！ |
| 左端が近い | left_edge | 左の端が近い。 |
| 左端が非常に近い | left_edge_urgent | 左、ぎりぎり！ |
| 身体が動いている | still_moving | まだ動いてる。 |
| 身体が静止・安定 | stable | 落ち着いた。 |
| 足元が本 | book | 本の上だ。 |
| 局所的に二つの道を検出 | branch | 近くで、道が二つに分かれてる。 |
| 左が細い／右が広い | branch_left_narrow | 左は細くて、右は広い。 |
| 左が広い／右が細い | branch_right_narrow | 左は広くて、右は細い。 |
| 砂糖皿を局所検出 | plate | 近くに、白い皿。 |
| 砂糖を局所検出 | sugar | 砂糖、見つけた。 |
| Goal内だが身体未安定 | goal_wait | ここで、落ち着こう。 |
| Unityが安定時間を含めてGoal確定 | goal | 着いた！ |
| UnityがRevealを開始した後 | reveal | ここを、歩いてきたんだ。 |
| 通信などの技術障害 | link_error | つながりが切れた。 |
| 確認済みゲーム落下 | fall | 落ちちゃった。 |
| Retry（前回右端VERY_NEAR） | retry | 前は、右の端が近かった。 |
| Retry（前回左端VERY_NEAR） | retry | 前は、左の端が近かった。 |
| Retry（端情報なし） | retry | もう一回。 |

右左ともVERY_NEARの場合は右の観測だけを採用する。「右から落ちた」とは断定しない。
記憶は直前のground、lastAction、左右edge観測だけ。原因推測はしない。
Retryで一度参照したら破棄し、技術障害通知でも破棄する。
同一会話内のRetryを対象とする。会話停止・再接続では記憶を破棄し、復元したふりをしない。

## 実装・適用

- 共通音声プロンプトへ、局所観測のみ・短文・質問では非操作というルールを適用。
- Bridge既存の単一control WebSocketに `blind_run_cue` を追加。契約は
  [blind-run-script-v1](../../Contracts/bridge-v1/blind-run-script-v1.md)。第二のTCP/controllerは作らない。
- Bridge内の台本選択器がcueごとの厳密な観測条件を確認し、選択行だけを既存GPT Live appendへ渡す。
- `chat_only` は拒否。身体制御を有効化する操作や所有権切替は台本処理に追加しない。
- 通常の神経変化による自動解説は、この台本が開始された会話中は背景情報に留める。
- 質問の応答材料は直近の局所報告と神経要約。局所報告が750msを超えたら不明と扱う。
  初版は完全な周囲スナップショットではなく、直近の一つの報告のみ。距離・slope等の網羅的回答は未対応。
- 新しい会話には一般ルールだけ入り、intro通知前はステージ開始も地形も捏造しない。

公式の[GPT Live prompting](https://developers.openai.com/api/docs/guides/live-prompting)と
[context append](https://developers.openai.com/api/docs/guides/live-delegation)に合わせ、台本をBackendに保持する。
append送信成功は発話完了・プレイヤーが聞いた証明ではない。言い換えやタイミングも実音声での検証が必要。

## 既存実装の確認と未実装

- Flyは `UnityProject/Assets/VisualDemo/Editor/FlyGroundedRealismBuilder.cs` 等の既存Builder／Config経路。
  新しいPhysicsRigを作らない。
- Sceneは既存の `FlyGroundedRealismDemo.unity`、`NativeConversationTest.unity` 等を確認。
  Blind Sugar Run専用Sceneは今回の調査では見つかっていない。
- 音声は既存 `ConversationAdapter` とUnity `ConversationSessionController`／`BridgeConversationSocket`。
- Actionは既存 `player_intent → ControlArbiter → submit → BrainAdapter → MaleCNS`。
- Unity側producerの追加状況は末尾の「Unity通知の接続」を参照。以下の未実装・検証記録はBackend初版時点のもの。
- World非表示、センサー、落下判定、Goal安定判定、Final Revealの実装・操作は今回の変更対象外。
  Revealを削ったのではなく、実際のReveal開始後に発話する台本を準備した。

## 検証と次のGate

実施：構文検査、26定型cue×ja/en、fall/retry、厳密evidence、旧sequence、古い観測、
不正型、Goal前Reveal拒否、技術障害を落下扱いしないこと、8人格／言語プロンプト、
既存Bridge経由の受信処理をスタブで検証。新しいテストファイルは作成していない。

未実施：課金API、実音声、実センサー、Windows実Brain＋Unity、Blind完走、失敗後の攻略改善、Reveal。
サーバー再起動・Git commit/pushは行わず、稼働中への反映は未確認。`ready=false`を維持。
最新指示のPhase 1〜4の実ステージ／センサー／Blind UI検証後、Phase 5でこの通知口を接続して音声を検証する。
今回の成果は台本とBackend受信準備であり、Phase 1〜7を通過したという報告ではない。

## Unity通知の接続（2026-09-13）

既存BlindSugarRunSessionが[BlindSugarRunNarrator](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunNarrator.cs)を自動追加し、同じConversationSessionControllerとcontrol WebSocketへ場面通知を送る。Sceneへの手作業でのコンポーネント追加は不要。
台本本文・全cue一覧・地図はUnityから送らず、Backendの台本JSONを引き続き正本とする。
voice／custom personaの設定は保持し、同じ場面の一言を現在の声色で表現する。

- 開始と操作練習は現在の会話・ゲーム進行に合わせる。局所観測は既存FlyTerrainSensorと実身体の状態を使う。
- 定規は身体前方0.75／1.5 Reachの2地点から下向き2 Reachの局所Raycastで実際に検出する。検出したBoxColliderの長軸から左右／正面を選び、不明形状や45度を超える横向きは方向を断定しない。
- 古い通知は送信待ち時間を含めて750msで破棄する。introのqueued応答を待ってから後続通知を送り、未確認の場合は現在の開始状態を新sequenceで再通知する。
- 新しい会話ではrun・観測・一度きりの台詞をリセットする。epochだけの変更ではBackendと同様run／sequenceを維持し、観測を破棄する。
- 落下時の緊急停止と既存Retryを優先する。停止に伴う音声終了で落下の一言が再生されない場合があり、発話のために停止を遅延しない。
- 既存Retryは会話を再開するため、Backendの同一会話内retry記憶を跨いで復元しない。
- Goal安定判定とFinal Revealは後続のゲーム側実装で接続した（[Goal／Reveal](../windows/Blind-Sugar-Run-Goal-Reveal.md)）。分岐・砂糖の意味的な局所検出は未実装。確認していない地形のセリフは送らない。

`tools/test_blind_run_script.py` は台本選択器の純粋な回帰検査であり、Unity／Brain／GPT Liveの代替試験ではない。
26定型cueのja/enと型付きevidence、intro順序、観測期限、旧run/sequence、余分な地図キー、
発話頻度、fall/retryの記憶破棄、障害と落下の区別、Goal前Reveal拒否を確認する。

検証結果：上記回帰5件に合格（26定型cue×2言語のsubtestを含む）。Unity 6000.5.9f1の既存Editor用response fileを使い、同梱Roslynで新規Narratorを含むAssembly-CSharpを別出力先へコンパイルして終了コード0、error 0。既存コードの非推奨API等のwarningは残る。
記録は `artifacts/blind-run-script-integration/compile-result.json` と `compile.log`。
これはライブEditorでの再コンパイルやPlayerビルドではない。

対象プロジェクトを使用する既存Unityプロセスがあり、この作業の所有プロセスとは確認できないため停止・再起動・ビルド操作はしていない。Windows実Brain／GPT Live／Unityでの場面発話、発話のタイミングと聴感は未検証。既存exeは再ビルドしていないため、配布Playerへの反映にはこのソースでのビルドが必要。
