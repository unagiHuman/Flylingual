# Brain・GPT Live の Mac／Windows 共通設計ルール

作成日: 2026-09-12。これは合意済みの正本設計であり、実装・実測の進捗は別紙 [Brain-GPTLive-Bridge 統合手順](integration/Brain-GPTLive-Bridge.md) に記録する。本書を新しい統合の実測証拠にしない。統合設計について旧手順書と矛盾する場合は本書を優先する。

## 1. 正本と責務

作業対象は Flylingual リポジトリだけとする。Mac では Brain、共通 Bridge、翻訳、接続切替サービスを開発する。Windows では Unity ゲーム、身体、HUD、音声、出力抑止、UI を開発する。ただし開発担当 OS と実行 OS は分離し、同じ Python ソースを Mac／Windows の双方で使う。

Bridge はゲーム／クライアント側に配置する。Unity は常に同じホスト上のローカル Bridge へ接続し、Bridge が Windows Brain（localhost）または Mac Brain（TCP）へ接続先を切り替える。Mac で Bridge を開発するときも同じコードで Mac Brain、必要時は Windows Brain に接続する。旧案の「windows-to-mac では Bridge が Mac 側」という配置は廃止する。

Brain 操作の client は Bridge だけとする。GPT 会話接続は Brain 切替から独立させる。ただし旧 Brain に基づく未完了操作・説明は、切替後に継続せず破棄または過去情報として扱う。

責務部品は次のとおりとする。

- `BrainAdapter`: Brain の接続、既存 protocol、状態、frame、ack、停止を扱う。
- `BrainTargetManager`: target、transport、session 世代、接続切替と解放確認を管理する。
- `ControlArbiter`: manual／GPT／解説の排他、期限、重複、緊急停止を管理する。
- `BrainStateTranslator`: BrainFrame の状態・神経活動を決定的に要約し、会話側がキャラ表現にするための根拠を渡す。
- `PlayerIntentTranslator`: プレイヤーの言葉・音声から得た意図を、許可された既存 Action の提案へ変換する。
- `ConversationAdapter`: 選定済みの会話サービスとの接続を隔離する。
- 共通設定／起動管理: profile 検証、ローカル所有 process の起動停止、診断を行う。

推奨構成は次のとおりである。

```text
Unity（ゲーム・身体・HUD・音声・入力・出力抑止）
  │ localhost の Brain 互換 TCP ＋ 別の会話／切替制御経路
  ▼
Bridge（Unity／ゲーム側。共通 Python）
  ├─ BrainAdapter ── Windows localhost または Mac TCP ── Brain
  ├─ BrainStateTranslator / PlayerIntentTranslator
  ├─ BrainTargetManager / ControlArbiter
  └─ ConversationAdapter ── 選定済み会話サービス
```

## 2. 接続、profile、配置

profile は OS 分岐ではなく、次の独立設定の組合せとする。

- `endpoint` と `transport`
- `backend` と `data` と `calibration`
- `brainMode`: `LIVE`／`REPLAY`／`MOCK`
- `conversationMode`: live／off／mock
- `controlOwner`: manual／gpt／observer（解説のみで操作権なし）
- Bridge bind、timeout、session／epoch 方針
- ローカル Python、data、audio のパス

Mac だから MaleCNS、Windows だから Replay といった暗黙分岐を作らない。同一 commit のまま、ソースや Scene を編集せず、profile と端末固有設定だけで切り替えられることを合格条件とする。

設定優先順位は CLI > 許可リスト内の環境変数 > Git 除外の local.json > 選択 profile > 共通既定値。未知キー、不正ポート、欠損パスは起動前にエラーとする。相対パスは cwd ではなく Flylingual ルートから解決する。backend／data／calibration の期待値が異なる接続は、自動的に同等と扱わない。

配置は以下を正本とする。共通Bridge側は実装済み、Unity側は別gate。詳細な実装・実測状況は統合手順を参照する。

```text
Runtime/Bridge/                         共通 Bridge、adapter、arbiter
Runtime/Config/profiles/                endpoint 等の共有 profile
Runtime/Config/local.example.json       ローカル設定の例
tools/dev.py                            共通 doctor／起動管理
UnityProject/Assets/RuntimeIntegration/ Unity 接続、HUD、音声、抑止
Contracts/bridge-v1/                    追加制御契約と小さい fixture
Docs/integration/                       両 OS の手順
```

端末固有の IP・絶対パスをコードへ固定せず、Git 除外の local 設定へ置く。localhost やポート、相対パス等の共通既定値は profile で管理する。API key は Bridge ホストの環境変数から読み、Git、Unity、起動引数、ログには保存しない。通常は localhost、遠隔接続は SSH tunnel を優先する。直接 LAN 接続時は認証、暗号化、接続元制限を必須とし、無認証 TCP 公開をしない。local launcher は自己所有 PID だけを停止し、remote process を勝手に起動・停止しない。Python 環境は各 OS で再構成し、NPY 等の大きなデータは Git 外で hash 照合する。

既存契約の `BrainFrame`、motor、status、ack、error は維持する。requestId mapping、epoch、sequence は各 session に対応付ける。追加のidentity／release観測は `Contracts/bridge-v1/protocol.md` に定義する。未実装の観測を実装済みと表示せず、既存 `ready=false` を勝手に変更しない。transport の接続状態（connected／disconnected／release unknown）と Brain の `ready` は別状態として観測・表示する。状態を見るためだけの操作 client は作らない。

Brain 互換 TCP には会話・切替・操作権の未知 message を混ぜず、別の制御用 WebSocket で扱う。Bridge は上流 requestId を一意に採番し、Unity requestId／GPT commandId との対応を保持する。Unity 向け ack／appliedRequestId は対応 ID に戻し、GPT 由来は Unity 要求と衝突しない未対応 ID とする（0 の予約・互換性を契約 gate で検証する）。原本 ID と raw frame を記録し、神経値と motor は改変しない。

通常接続中は各 Brain server の persistent 状態を維持し、通常 Action で reset しない。一方、別 Brain への切替時に脳／decoder 状態を跨機移植してはならない。

## 3. Brain 操作と GPT 会話

GPT は 6 Action（`STOP`、`FORWARD`、`TURN_R`、`TURN_L`、`FORWARD_R`、`FORWARD_L`）の提案だけを行う。Action は既存刺激、MaleCNS、raw 神経出力、既存 decoder、motor の経路を通る。GPT が神経 ID、強度、weight、motor を直接変更してはならない。

manual と GPT の操作権は明示的に排他切替する。observer は解説のみで操作できない。解説音声は操作入力としてフィードバックしない。緊急停止は Unity で即時に出力抑止し、明示解除までラッチする。刺激 OFF の通常 `STOP` とは区別する。曖昧な意図や未対応動作を勝手な Action へ変換しない。

操作提案は action、commandId、controlEpoch、validForMs を持ち、Bridge の単調時計で期限・上限を管理する。重複、期限切れ、旧 session、非所有者の要求を拒否し、切替・再接続で未適用要求を自動再送しない。GPT 操作中に GPT 接続断／期限切れが起きたら STOP を要求し Unity 出力も抑止する。manual 中は会話障害だけで操作権を奪わない。Unity／Bridge 制御路断でも Unity が独立に抑止し、発話中断だけを Brain 停止完了と扱わない。

BrainFrame からの翻訳は、観測 → 決定的な要約／変化検知 → キャラ表現の順とする。要求 Action だけで実応答を断定しない。「気持ち」は神経活動に根拠を置く擬人的表現であり、実際の感情を読み取ったとは主張しない。実移動、崖、接触などは Unity 観測という別入力を根拠として区別する。不明・stale は不明・stale と表示する。frame 要約、変化検知、発話頻度制限を設ける。

「指示受付」「appliedRequestId による Brain 適用確認」「神経応答」「Unity で観測した身体動作」を区別し、受付 ack だけで動作完了と説明しない。Brain 計算と Bridge／会話通信は別プロセスとし、音声デバイスは Unity の AudioAdapter で OS 差を吸収する。会話実装は公式資料に基づきGPT-Live primary WebSocket／client delegationとResponsesによる意図翻訳を選定し、`ConversationAdapter` に隔離した。モデル・依存・イベントは統合手順を参照する。選定・実装と実API受入れは区別する。GPT-Live と Realtime API を名前だけで同一視しない。

## 4. 安全な Brain 切替

切替は次の順序を規範とする。

1. 出力抑止を有効化し、新規操作の受付を停止する。
2. 旧 Brain へ `STOP` を期限付きで試行する。
3. 旧接続タスクの終了と controller 解放を確認する。
4. `target`／`session` 世代と `controlEpoch` を更新する。
5. 旧 frame、pending request、遅延応答、旧 GPT 操作を破棄する。
6. 新 Brain の backend、data、calibration、source、session、新規 frame を確認する。
7. 停止状態を確認し、明示的な再開操作だけを受け付ける。

いずれかに失敗したら停止状態を維持する。無断 fallback、未適用操作の再送、旧操作の持越しは禁止する。ネットワーク断などで旧 server の解放が観測できない場合、切替成功としてはならない。

解放の証拠は server の session／controller ID にひも付いた release event・ログまたは既存の読み取り専用管理情報とする。ESTABLISHED がないことだけでは内部 slot 解放の直接証明にならない。観測手段は実装時に契約化し、観測不能時は `release unknown` として停止する。新 Brain に残留活動があれば STOP と新規 frame による確認を期限付きで行い、停止確認ができなければ再開しない。

新規 frame だけが鮮度を更新する。既存の 0.75 秒 stale 判定を無制限に延長しない。heartbeat、同一 frame の再送、会話接続状態で鮮度を更新してはならない。

## 5. 表示、観測、ログ

HUD では execution OS、target、backend／data、calibration、`LIVE`／`REPLAY`／`MOCK`、GPT 接続、control owner、frame age、出力抑止理由を分けて表示する。GPT 接続済みを Brain ready と扱わない。

ログには instance、session、controller の active count、connect／disconnect／release、source・data・calibration hash、last frame、sequence、epoch、requestId／commandId 対応、accepted／applied／superseded／expired、stale、停止理由、切替各段階、step 時間、同一プロセス時計による E2E を記録する。異なる PC の時計を引かない。会話本文と音声の常時保存は既定で無効にする。実装済み観測は追加契約に記載し、観測できない状態を成功とみなさない。

## 6. 実装順と合格条件

実装順は、(1) 共通設定と adapter、(2) 両方向の安全な切替、(3) text／mock を先行した双方向翻訳、(4) GPT 接続と音声、(5) Windows Unity 受入れ、とする。

各段階で、同一 commit の profile 切替、6 Action、再接続、遅延応答、解放、不正指示、stale、manual／GPT 競合、API 断、切替中入力を確認する。Windows ゲームから Windows Brain → Mac Brain → Windows Brain を往復し、Mac 側でも同じ実装のローカル接続を検証する。Mac から Windows Brain への接続は必要時に明示して検証する。実 Brain、実 API、Unity は別々の gate とし、新しい統合の性能・操作感は新規実測で判定する。既存 checkpoint の成果は保持するが、mock／fixture の合格を実 Brain の合格に読み替えず、ready を自動昇格しない。

## 7. 運用と未実施事項

doctor は設定、依存、data hash、port、自己所有 process の状態を確認し、課金 API 呼び出しをしない。launcher はローカル所有 Brain の初期化と transport 利用可能状態を確認して Bridge を起動する。利用可能状態と製品の ready は区別する。両 OS の Python 環境、依存版、source hash、data hash、測定母数、RSS、計算時間、E2E を gate ごとに記録する。

Flylingual の既存運用ルールに従い、main へ直接 commit／push し、push 前に origin/main を取得して差分を確認する。force push は行わない。共通Bridgeの実装・Mac実Brain＋会話MOCKの実測は統合手順へ記録した。実API接続、実音声、Windows Unity、跨OS往復・操作感は未検証であり、`ready=false` を維持する。
