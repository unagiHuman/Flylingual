# DNp01実測実況の追跡と日英Player検証（2026-09-14）

日英の実GPT Live＋Windows実Brain＋Unity Playerで、DNp01の左右実測値を含む実況とAPI受理を確認した。最終両試験は `visual_threat_pass`、fresh=true、STOP適用、exit 0。途中にbody TCP切断・再接続があるため、連続無障害の実証とはしない。

## 最終実装

- `ConversationAdapter.append(..., trace=...)` の実送信を `sent`、APIからの対応する通知を `accepted` として記録。実APIが返す `client_event_id` を元の送信IDに照合する。同フィールドが存在しない場合だけ `event_id` を使用。不一致時にFIFO推測をしない。
- 記録はchannel、context generation、content SHA-256、固定許可キーの観測traceだけ。本文・音声・認証値を常時保存しない。最大128件、相関期限30秒。clear／stop／切断で破棄。未知の通知は `unmatched` とし、一般の未追跡文脈の通知もこの区分になる。
- 警告中の最初の正のDNp01実測窓を一件保持する。利用期限は8秒で、後続frameで年齢を更新しない。現在のBrainがfreshで、session／instance／epoch／会話generation／runが一致する場合だけ利用できる。通常STOPは刺激を取り消すが、直前の実測は過去情報として残す。
- 検証済み `swatter_escaped` cueの文脈通知を、実測がある場合だけ一度の短い実況へする。既存の3秒発話間隔用時刻も更新。危険警告やAction経路は変更しない。neural無効・実況を減らす指定・旧scope・期限切れなら追加しない。
- 短い実況は「さっきのDNp01は右120、左140 Hz、予告は解除された」／“Earlier DNp01: right 120, left 140 Hz; warning cleared.”のように測定値を先に置く。値は同じ原Brain窓から取得し、固定の応答を注入しない。恐怖や回避成功を測定したとは言わない。

Brain入力・重み・decoder・physics・ゲーム性能は変更していない。新しい神経設定定義はない。追加契約は [bridge-v1](../../Contracts/bridge-v1/protocol.md)。

## 最終実Playerの結果

```powershell
& tools/neural_player_trial.ps1 -Name visual-commentary-ja-short -Language ja -Question 0 -VisualThreat
& tools/neural_player_trial.ps1 -Name visual-commentary-en-short -Language en -Question 0 -VisualThreat
```

両試験は `127.0.0.1:18766`、MALECNS_EXPERIMENTAL／LIVE、ready=false。マイクなしの固定テキスト試験で、外部送信はユーザー許可済み。試験中のローカル自由記述は除外、終了時に元設定を復元。実Brainでの前進・警告・回避を使う。実況後のSTOPまでの前進時間を診断時だけ3→5秒にし、後続質問の待ちを11→9秒へ短縮して総待機時間を維持した。初期位置を診断用に一度移動するが、接触・危険イベント・motorの注入はしない。

| 観測 | 日本語 short | 英語 short |
|---|---:|---:|
| Brain unique frame数（起動待ち含む） | 264 | 263 |
| 操作区間sequence | 14→267 | 16→272 |
| neural観測／身体相関 | 260／66 | 261／68 |
| 初回前進距離 | 2.739m | 2.872m |
| 果汁接触／警告開始／解除 | 各1 | 各1 |
| 感覚ON窓／OFF窓 | 2／12 | 3／12 |
| ON窓DNp01発火合計 R/L | 12／14 | 19／21 |
| 実況に使った原窓 | seq199、50ms | seq203、50ms |
| 原窓 R/L | 6/7発火＝120/140Hz | 6/7発火＝120/140Hz |
| Unity frame p95 | 16.73ms | 16.70ms |
| Player RSS sample最大 | 575,582,208 bytes | 574,078,976 bytes |

日本語の実出力transcriptは「さっきのDNp01は右120Hz、左140Hz、予告はもう解除…」。左右の測定値は両方一致したが、解除の語尾は次の発話へ切り替わり未完。英語は “Earlier DNp01: right 120, left 140 Hz; it's cleared.” を確認。これらはAPI出力transcriptの確認であり、スピーカーを耳で聞いた音響品質試験ではない。音声入力は行っていない。

日本語commentaryのsent/acceptedは同じevent ID `08c3d5cb-e3d5-4f6b-95f1-8c078a2a0a0a`、英語は `1f392e4d-b35c-4544-b3f3-dd6cfef79b3b`。いずれも `current=true`、`correlationField=client_event_id`、request -1、environmentSequence 9。元rawのsession/instanceと一致するtraceを確認した。API受理と左右数値の出力を別々の証拠として扱う。

同一Bridge単調時計のsent→acceptedは日本語1,110ms、英語766ms。発話開始・終了までの遅延とは区別する。visual観測のunique sequence数は日本語14、英語15で、重複による発火数の水増しはなかった。

日本語sequence229、英語233付近にbody TCP切断ログがあり、その後に復旧して最終fresh/STOP判定を通過した。終了付近にはcontrol inactiveも記録される。最終result.errorは空だが「試験中に障害なし」とは書かない。質問応答には短い／案内寄りの断片が残り、一般的な会話品質の完成判定にはしない。

## 検証履歴と限界

原本は `artifacts/neural-feedback/` の各試験prefixに対応する `.json`、`.json.events.jsonl`、`-metrics.json`、`-player.log`、`-bridge.jsonl`とローテーションファイル。

| 試験prefix | 判定と得られた証拠 |
|---|---|
| visual-commentary-ja | 後半fresh=false、全体failed。ON/OFFは成功。独立した実況待ちが8秒で失効。API通知がclient_event_idを返すことを確認 |
| visual-commentary-ja-v2 | Player pass。ON/OFF thinking受理確認。解除cueが通常speak=falseであるため実測実況なし |
| visual-commentary-en-final | Player pass、commentary受理、右120まで実況。左値は未完 |
| visual-commentary-ja-final | Player pass、commentary受理、DNp01という名前までで数値は未完 |
| visual-commentary-ja-short / en-short | 最終短文化版。Player pass、受理、左右値とも一致 |

不合格や途中の未完結果を成功へ書き換えていない。再試行は各回のコード／計測不足の修正後に限定した。最終の日本語語尾、間欠的TCP再接続、一般質問の応答品質、目視、マイク／スピーカー品質、ゴール到達までの長時間プレイは残る確認事項。

関連純粋テスト74件PASS（2.098秒）。現行Unity CLIで編集モードからコンパイル完了、errors=[]、compilationFailed=false。最終Dev-Localビルド11:43:58→11:44:21 UTC、Succeeded。BuildReportの1 errorはCLI応答5秒timeoutだけであり、ビルドの失敗とは分けて確認した。

Brainのgraph/config/sourceは [前段の実測](Visual-Threat-Game-Integration.md) と同じ。全CNS 166,700細胞、19,670,694格納edge、window50ms、dt0.1ms、seed20270101。Python3.10.12、NumPy1.24.3、Numba0.61.2、llvmlite0.44.0。今回の最終source hashは `artifacts/neural-feedback/visual-commentary-short-source-hashes.json` に保存（conversation `c062b7ffadf7a6a27186b57f49ed63f72b8f0048b93ba69f54ff23f7fa14d281`、visual feedback `1de433d75301287462590618532b4abe0c1947453f6180fb1d57fbe014ee8ff2`、server `24f4e55d2da9713a30d2fda71961c7eee409e18ede52555760b508600033fcdb`）。RSSはsample最大であり生涯ピークやBrain単体値の保証ではない。

## 後続の原因調査（2026-09-14）

上記の質問直後のTCP切断は、既存の `instructions` チャネルを前回の検査追加で拒否していた回帰と特定し、許可を復元した。強化した日英Player試験ではこの例外は消え、質問後の再移動は成功したが、別のBrain窓計算遅延で安全停止し、連続安定性は未合格。旧試験の結果は変更しない。詳細は [質問後の接続検証](Question-Connection-Validation.md) を参照。
