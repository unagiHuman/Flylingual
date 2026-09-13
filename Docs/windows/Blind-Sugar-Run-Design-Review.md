# Blind Sugar Run 詳細設計書・受領確認

ユーザー提供の[詳細設計書](Blind-Sugar-Run-Detailed-Design.md)を全102節（第0〜101節）受領した。提供原文を変更せず保存し、添付ファイルとのSHA-256一致を確認した。本メモは文書上の照合結果であり、実装・動作検証の合格を意味しない。

## 文書の位置付け

- [プロトステージ仕様書](Blind-Sugar-Run-Prototype-Spec.md)：会話によるBlind Play、3 Challenge＋Goal、局所観測、失敗の振り返りというゲーム体験の基準。
- [詳細設計書](Blind-Sugar-Run-Detailed-Design.md)：その実装構成、画面遷移、制作順、受入れ条件。旧仕様と異なる具体事項は、今回受領した詳細設計を基準に整理する。
- [先行企画書](Level-Design-Proposal.md)：検討履歴として保持。6区間本編や中断保存を今回のMVPへ追加しない。

詳細設計第0節が指定する優先順（最新ユーザー指示、AGENTS.md、共通設計正本、詳細設計書）に従う。

## 確認できた具体化・変更

| 項目 | 今回の基準 |
|---|---|
| ゲーム全体 | Boot、Title、Prototype、StageClear、GameOver、GameClearの6シーン |
| 画面遷移 | GameFlowServiceへ集約し、多重ロードを防ぐ |
| 落下 | 単なる下降ではなく、Fly rootのKillVolume進入でGameOver。Retryは同ステージを再ロードする |
| 記憶 | Retryでは前回の失敗を保持。New GameとTitleへのQuitではrunを破棄する |
| ゴール | 安定判定→入力抑止・STOP→Reveal→StageClear→GameClear |
| UI | UI Toolkit、UXML／USS／Presenter分離。通常プレイではWorldを隠す |
| 制作順 | Unityで通行可能な地形を確定してから、BlenderMCPで外観を制作する |
| 検証 | Windows実BrainでのLive検証。通信障害はConnectionErrorとしてゲーム失敗と分ける |
| 最初の実装範囲 | GameFlow、基本UI、空のプロトシーン。Brain／GPT／Blenderの変更は含めない |

## 既存設計に従って解釈できる点

1. **接続経路（詳細設計第80・83節）：** 第80節の「Unity→127.0.0.1:18766」は経路の略記として扱う。共通設計ではBrainの操作クライアントはBridgeだけであり、通常統合はUnity→同居Bridge→Windows Brainを維持する。[Windowsローカル構成](Windows-Local-Stack.md)の記載ではBridge motor TCPが18770、Brainが18766。実行時は現在の設定と照合し、Unity側にBrainへの第二の直接接続を追加しない。
2. **緊急停止（第60節）：** STOP要求と新規Action抑止に加え、共通設計が定めるUnity側の即時出力抑止を維持する。通常STOPだけでMotor Cut完了とは扱わない。速度の強制ゼロ化や身体固定は行わない。
3. **フェーズと実Brain（第77〜80節）：** 空シーンのボタンによる遷移確認と身体の通行検証を分ける。実Flyを動かす第79節の検証にも、第0節とAGENTS.mdのWindows実Brainルールを適用する。
4. **Action名（第49・56・61節）：** HUD例のTURN_LEFTは表示上の表現として扱い、送信する既存ActionはTURN_Lとする。NONEは会話側の「移動要求なし」であり、Brainへ送る第7のActionにしない。

## 実装前に詰める事項

以下は未決事項の記録であり、提供原文への追加仕様ではない。既存コードを調査したうえで実装計画に具体化する。

- **障害中の落下と復帰（第14・59・93節）：** 出力抑止後も物理は進むため、ConnectionError中にKillVolumeへ入る可能性がある。その際の失敗通知の抑止、接続復旧後の再開位置、明示再開までの手順が必要。障害と落下が同時に起きた場合のイベント優先順位も定める。
- **シーン遷移と既存ランタイムの寿命（第18・66・67節）：** Unityシーンを再ロードするだけでは、別プロセスのBrain状態や古い会話要求まで初期化できたとは言えない。既存の停止・切断・世代管理を使い、旧シーンの遅延Actionが新しいFlyへ届かないようにする。Brain dynamicsの変更や無条件resetを要求するものではない。
- **受け皿の扱い（旧仕様第6節と詳細設計第15・16節）：** 旧仕様のOpenBookCatchを残すか、プロトではKillVolumeによるRetryに統一するかは地形の具体化時に整理する。詳細設計ではKillVolume進入がGameOver条件であり、足場への通常着地まで自動的にGameOverにはしない。
- **Blind表示の切替（第50・67節）：** ステージ読込直後、UI初期化中、画面比率変更、ConnectionErrorからの復帰でもWorldが一瞬見えないことを受入れ項目に含める。公開版のDeveloper表示は無効化する。

## 今回の作業範囲

詳細設計書の受領・原文保存、既存文書との照合、参照案内の更新まで。コード調査による実装計画の確定、Skill新設、Unity操作、シーン制作、API呼び出し、Brain起動、コミット・プッシュは行っていない。
