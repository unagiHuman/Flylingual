# Brain・GPT LiveのMac／Windows共通設計案

作成日: 2026-09-12。設計のみ。記載する追加ファイル・設定・CLIは未実装。

## 1. 決定案と前提

MacとWindowsで同じソースを使い、実行場所と接続先をプロファイルで切り替える。Brain計算、GPTとの会話、Unityの描画・物理を別の責務とする。

GPT Liveは暫定的にOpenAI Realtime APIを指すと仮定する。別サービスの場合はConversationAdapterを置き換える。GPTが操作する用途を想定するが、会話・解説だけの用途もobserver設定で対応する。

正式な作業対象はFlylingualリポジトリ。以下の構成はそのルートを基準とする。隣接するFlytestは作業対象にしない。

## 2. 現物確認

- 両コピーにBrain、UnityProject、Contractsがある。GPT Liveという名前の接続実装は今回の検索では見つからなかった。
- FlylingualのBrainTcpClientはTCP/NDJSONを使用し、ConfigureEndpointがある。WindowsReplayDemoには-brainHost/-brainPort/-demoLiveがある。
- 既存ActionはSTOP、FORWARD、TURN_R、TURN_L、FORWARD_R、FORWARD_L。Action→刺激→神経活動→decoder→motorの経路を維持する。
- protocol-existing.mdではサーバー側の操作元排他は未実装。GPTを追加の直接操作clientとして接続すると競合する。
- ConfigureEndpointは接続タスク終了前には使用できない。既存Disconnect直後の即時切り替えを前提にしない。
- Windows native検証文書にはMaleCNSの起動・TCP確認の追記がある一方、遅延の受入れは未達と記録されている。本設計は現在の性能・Mac実機動作を再検証したものではない。

## 3. 構成

```text
Unity（表示・物理・操作UI・音声入出力）
  │ Brain互換TCP/NDJSON       │ 会話・音声用WebSocket
  └──────────────┬──────────┘
          Bridge Service（共通Python、独立環境）
            ├─ ControlArbiter：操作権・期限・緊急停止
            ├─ BrainAdapter ── TCP/NDJSON ── Brainプロセス
            └─ ConversationAdapter ── WebSocket ── GPT Live
```

BridgeだけがBrainの操作clientになる。UnityはBridgeのBrain互換ポートへ接続する。Bridgeは既存status/ack/brain_frame/errorを扱い、神経値やmotorを改変しない。追加の会話・操作権情報は別のWebSocketへ流し、既存BrainTcpClientの未知messageエラーを避ける。

GPTの出力は許可されたActionの提案として検証する。motor値・神経ID・刺激強度をGPTから直接設定しない。会話応答では「指示受付」と「Brain適用確認」を区別し、appliedRequestIdの確認前に実行済みと断定しない。

音声デバイスはUnity側のAudioAdapterで扱い、取得形式から合意した通信形式へ変換する。Macのマイク許可、Windowsのデバイス選択、サンプルレート差はここで吸収する。初回PoCはテキストで接続と操作権を確認し、その後音声を追加する。Brainシミュレーションと音声通信は別プロセスのため、脳計算で会話イベントループを塞がない。

Realtime WebSocketの利用は公式SDK資料に記載がある。本案はPythonを採用候補とする設計判断であり、Ruby SDKを導入する提案ではない。モデル名・イベントschema・音声形式・利用可能性は実装開始時に選定APIの公式仕様で固定する。
参考: https://developers.openai.com/api/reference/ruby

## 4. 切り替え単位

| プロファイル案 | Unity | Bridge＋GPT接続 | Brain |
|---|---|---|---|
| mac-local | Mac | Mac | Mac |
| windows-local | Windows | Windows | Windows |
| windows-to-mac | Windows | Mac | Mac |
| offline-replay | 任意のOS | 起動不要 | 実測fixture |

通常は全サービスを127.0.0.1へbindする。windows-to-macのみ、明示した信頼できる接続でBridgeに到達させる。初期案はSSHポート転送とし、BrainはMacのlocalhostに残す。直接LAN公開する場合は別途Bridgeの認証・暗号化・接続元制限を実装する。生TCPを無認証で公開しない。

OS、backend（shiu/malecns）、brain mode（live/replay/mock）、conversation（live/off/mock）、control owner（manual/gpt/observer）は独立設定とする。MacだからMaleCNS、WindowsだからReplay、という分岐は作らない。接続失敗時の自動Replay切り替えも行わない。

```text
Runtime/Bridge/                 共通接続・会話・操作権管理
Runtime/Config/profiles/        Git管理するプロファイル
Runtime/Config/local.example.json
tools/dev.py                   共通doctor/up/down入口
UnityProject/Assets/RuntimeIntegration/  設定読込・状態UI・音声
Contracts/bridge-v1/            新規契約と小さいfixture
Docs/integration/              両OSの共通手順
```

設定の優先順位はCLI > 許可リスト内の環境変数 > Git除外のlocal.json > 選択プロファイル > 共通既定値。未知キー・不正ポート・欠損パスは起動前にエラーにする。相対パスはcwdではなくリポジトリルートから解決する。

共通プロファイルにはbackend、bind先、ポート、mode、タイムアウトを保存する。local.jsonにはPython/Unityの実行パス、データルート、音声デバイスを保存する。APIキーはBridgeプロセスの環境変数から読み、Unityアセット・Git・起動引数・ログへ入れない。

Brainの既存Python環境は維持し、Bridgeの依存環境を分離する。Macのvenv、Cython生成物、Unity LibraryをWindowsへコピーしない。各OSで環境を作り、依存版とデータhashを記録する。大きなデータはGit外に置きmanifestで照合する。

以下は実装後の操作イメージで、現時点では実行できない。

```text
python tools/dev.py doctor --profile mac-local
python tools/dev.py up --profile mac-local
python tools/dev.py up --profile windows-local
python tools/dev.py up --profile windows-to-mac
```

doctorは設定・依存・データhash・ポートを確認し、課金API呼び出しはしない。upはローカル所有のBrainを起動してready状態を確認し、Bridgeを起動する。remote設定では外部PCのプロセスを勝手に起動・停止しない。終了処理は自身が起動したPIDだけを対象とする。

## 5. 操作権と障害処理

- manualとgptの操作権は明示切り替え。非所有者の移動要求は拒否する。緊急停止は常に優先し、解除までラッチする。
- GPT指示はaction、commandId、controlEpoch、validForMsを持つ新しいBridge内部契約とする。期限はBridgeの単調時計で管理し、上限を設定で制限する。長時間移動の具体的な期限は脳応答の実測で決める。
- Brainへは既存set_actionだけを送る。Bridgeが上流requestIdを一意に採番し、Unity requestIdまたはGPT commandIdとの対応を保持する。Unity向けack/appliedRequestIdは対応するUnity IDへ戻し、GPT由来のframeはUnity要求と衝突しない未対応ID（0）として扱う。原本IDとraw frameは診断ログへ残す。
- 操作権変更・再接続でcontrolEpochを更新し、古いGPT応答と期限切れ要求を破棄する。latest action winsで未適用になった要求はsupersededとして区別する。
- GPT切断・期限切れ時、GPTが操作権を持っていた場合はSTOPを要求し、Unityの出力抑止も有効化する。manual所有中は会話障害だけで操作権を奪わない。
- 通常STOPは刺激OFFであり、即座にmotor=0になる保証はない。緊急停止・通信障害時のactuatorゼロ化はUnity側で独立に行う。
- Brainから新規frameが来た時だけ転送する。heartbeatや同じframeの再送で鮮度を更新しない。Unityの既存0.75秒stale判定は維持し、会話制御路の切断にも別の出力抑止を設ける。
- プロファイル変更は停止状態で実施する。出力抑止→STOP送信を期限付きで試行→接続タスク終了待ち→frame/request状態破棄→設定更新→再接続→新sessionの状態・frame確認→明示再開の順とする。切断時に古い移動要求を自動再送しない。
- BridgeとUnityの双方でsession世代を持ち、再起動前のsequenceや遅延応答が新sessionへ混入しないようにする。

## 6. 表示と計測

HUDには実行先、backend/dataset、LIVE/REPLAY/MOCK、GPT接続状態、操作権、frame age、出力抑止理由を別々に表示する。Brainのready=falseをBridgeがtrueへ書き換えない。GPT接続済みをBrain準備完了と扱わない。

記録はsource commit/hash、OS・依存版、data/config hash、session、commandIdとrequestId対応、superseded、stale、切断、step時間、E2Eとする。E2Eは送信と受信が同じプロセスの単調時計で測る。異なるPCの時刻を引かない。音声・会話本文の常時保存は既定で無効にする。

## 7. 実装順と受入れ

1. 対象リポジトリとGPT Liveの意味を確定し、共通設定・doctorを追加する。両OSでパス解決と設定検証が一致すること。
2. GPTなしのBridgeを追加し、Unity→Bridge→Brainの6 Action、requestId対応、排他、切断、再接続を実測fixtureと実Brainで検証する。既存直結経路も残す。
3. MacでテキストGPT接続を追加する。mock会話で不正Action、重複、期限切れ、旧sessionの応答を検証した後、実APIで指示→適用確認を試す。
4. Macで音声入出力を追加する。マイク拒否、デバイス欠損、発話中断、音声切断を確認する。
5. 同一commitをWindowsへ取り込み、windows-localとwindows-to-macを検証する。プロファイル以外のソース・Scene編集なしに切り替えられることを合格条件とする。

契約・設定・操作権のテストは両OSで実行可能にする。通常CIは小さいfixtureとmockを使用し、実Brain／実API試験は別Gateで記録する。通信互換の合格と、脳計算の遅延・ゲーム操作性の合格を分ける。

Mac担当はBridge/GPT接続、Windows担当はUnityの設定・HUD・音声Adapter、Contractsは統合担当が順次編集する案とする。共有Gitの別checkoutを使い、ユーザー指示により両OSともmainへ直接コミット・プッシュする。プッシュ前にorigin/mainを取得して他方の変更を取り込み、force pushは行わない。既存Brain/decoder/物理の調整を接続開発へ混ぜない。

本作業の変更は設計書1ファイル。compile、サーバー起動、API接続、Mac実機試験、性能測定は未実施。次のGateはGPT Liveの意味を確定した後の共通設定実装。

## 8. Macへの引き継ぎ（2026-09-12）

ユーザー指示により、当面はMac側でBrain・GPT Live接続の開発を継続する。Windows側の実装は保留する。Windowsへ戻せる共通設定・通信境界の方針は維持する。現時点では設計のみで、接続先の変更やサービス起動は行っていない。
