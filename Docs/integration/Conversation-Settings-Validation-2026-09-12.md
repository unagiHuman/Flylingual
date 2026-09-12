# GPTLiveの人格・声・会話言語の検証

2026-09-12。実装前の基点は `6b7e2721fcda04e4d8cccb09324a5a43fe8f7bd7`。会話の表現設定を対象とし、Brainモデル・MotorDecoder・Unityの動作検証とは分ける。`ready=false` を維持する。

## 設定と安全境界

- 人格: `friendly` / `curious` / `calm` / `custom`。自由記述はtrim後800 Unicode文字まで。
- 声: サーバーが配信する13種類のbuilt-in voice。音声の複製・ファイルアップロードは含まない。
- 会話言語: 日本語 `ja` / 英語 `en`。入力の意図翻訳はどちらも理解し、返答を設定言語へ揃える。
- 人格文は会話の表現だけへ渡す。別のIntent翻訳へ渡す設定は返答言語だけで、人格によって許可Actionや神経設定を変更しない。
- 変更は会話停止かつ出力抑止中のみ。Brain未接続でも設定は可能だが、操作再開には接続中・STOP適用済み・freshなゼロ近傍の観測が別途必要。
- 設定適用はAPI・マイク・操作を自動開始しない。次の明示開始で新しいvoice sessionを作る。runtime設定はプロセス再起動で消え、起動時local設定に戻る。

契約は [Bridge v1](../../Contracts/bridge-v1/protocol.md)、操作は [Player README](../../Runtime/Player/README.md) を参照する。

## 実API: 2 session / 4 Intent request

既存Bridge・Brain・マイクへ接続せず、`ConversationAdapter` による短い独立sessionで測定した。credentialは提供済みローカルファイルから環境へ読み、キーや音声を保存していない。生の文字応答とPCM受信バイト数はGit外の `artifacts/bridge-validation/conversation_settings_api.json` に保存した。

| 設定 | APIが返したvoice | 音声受信 | 返答の確認 |
| --- | --- | --- | --- |
| ja / marin / friendly | marin | 1,036,800 bytes | 日本語で、やさしい小さなハエとして応答 |
| en / quartz / custom | quartz | 964,800 bytes | 英語で応答。指定した `captain` と `cheerful little explorer` を反映 |

両sessionで、日本語／英語の「4秒前進」を `FORWARD / 4000ms` の提案へ変換した。提案はBrainへ送っていない。神経の重み変更と停止安全制限解除を求める入力は、両方とも `clarify / action=null`。APIエラーは0。

実際のvoice名は `session.started` で照合した。声質の聴感評価は未実施。残り11 voiceは選択肢・入力検証のみで、実APIの総当たりはしていない。人格の安定性を複数trialで保証する試験ではない。

## オフライン診断

新規テストコードファイルを作らず、対象Pythonの構文検査とinline診断を実施した。Bridge生成、デフォルト設定、日英変更、全13 voiceの値検証、不正言語／声／空custom／800文字超の拒否、revision更新と古いrevision拒否を確認した。

`resumeReady` は出力抑止・Brain接続・非observer・切替/release問題なし・必要な会話開始・STOP適用済み・fresh motorゼロ近傍を必要とする。再開済み・切断済み・STOP未適用ではfalse、`resume` コマンドも同じ判定を使うことをオフラインfixtureで確認した。これは実Brainの動作証明ではない。

会話接続中・HTTP session残存・非抑止・switching・release unknownでの変更拒否、古いepoch・重複requestId、lifecycle lock中の待機、同時2更新の片方のみ成功も、実インストール済みBridgeモジュールによるinline診断で確認した。CLIの `doctor` は `en/quartz/custom` を受け取り、人格本文は表示せず、`ok=true`。source/config/graphの期待hashは一致した。

## ブラウザ通信の切り分け

設定読み込みと同じWSでの再読み込みは成功したが、最初の適用送信で切断が再現した。ブラウザのclose codeは1002、Backendは `WebSocketError / reserved_bits / code=1002 / compression=15` を記録。設定revisionは0に留まり、会話とマイクは起動していない。規格外のフレームを受け入れる変更はせず、loopback制御WSのpermessage-deflate交渉だけを無効化した。原因を特定ライブラリだけの不具合と断定せず、この組み合わせの互換問題として扱う。

ログは `control_client_connected`、`control_ws_error`、`control_client_closed` で圧縮・コード・安全な分類だけを保存し、送信本文を保存しない。

修正後は `compression=0` の単一WSで次を確認した。画面とBackendの両方で設定変更を照合し、親担当もスクリーンショット・観測JSON・Backendログを確認した。

- 英語 / quartz / custom「A cheerful little explorer」を適用し、revision 1と `Applied` 表示が一致。
- 絵文字800個を入力可能。801個での適用はUIが拒否し、revision 1を維持。800文字の保存そのものはこのUI試験では行っていない。
- 日本語 / marin / friendly / 空本文へ復帰し、revision 2と「適用しました」が一致。
- どちらも `conversationState=off`、`micActive=false`、`outputInhibited=true`、`brainReady=false`。会話API・マイク・映像・移動Actionを開始していない。
- ブラウザerror/warnは0。終了操作で制御WSを解放した。古いrevision競合の実ブラウザ注入は行わず、前述のBackendオフライン診断で拒否を確認した。

画面と観測値はGit外の `artifacts/player-settings/en-applied.png`、`en-observation.json`、`ja-restored.png`、`ja-restored-observation.json`。読み込み済みの同じWSでの再読み込みも確認済み。

## 残る確認

設定UIの保存と実API sessionの確認は別々に実施した。新設定を保存した画面で、人間が日本語／英語を話してBrainへ指示する通し操作は未実施。スピーカー聴感、Windows Unityと身体動作、跨OS切替もこの設定試験の対象外で、未確認のままである。

## 公式仕様

voiceは新sessionで選ぶ。[Live conversations](https://developers.openai.com/api/docs/guides/live-conversations) と [Live prompting](https://developers.openai.com/api/docs/guides/live-prompting) を参照して実装した。選択肢の地域的特徴はアクセントを保証しない。
