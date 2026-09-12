# 共通契約：2台のCodexを衝突させない

版1.0／2026-09-11 JST

## 1. 変更所有者

| パス／領域 | 所有者 | 備考 |
|---|---|---|
| `Brain/MaleCNS/` | Mac | データ選択、LIF、NT、readout、校正 |
| `Brain/ShiuBaseline/` | 原則freeze | Windows互換の最小変更だけ独立PR |
| `UnityProject/Assets/VisualDemo/` | Windows | Visual、HUD、デモScene |
| `UnityProject/Assets/FlyBrainPoC/` | Windows | 必要なmetadata表示・UI互換だけ |
| `UnityProject/Assets/FlyLocomotion/` | freeze | 新反射・CPG変更を自動で始めない |
| `VisualSource/` | Windows | Blender正本、asset出典 |
| `Contracts/` | 初版Mac、その後単独の統合担当 | 同時編集しない |
| `Docs/mac/` / `Docs/windows/` | 各担当 | 実測とhandoffを分離 |

Git運用と開発agentの役割は[AGENTS.md](../AGENTS.md)を正本とする。2026-09-12のユーザー指示により両OSともmainへ直接commit／pushし、旧機能別ブランチ方針は廃止する。2台で同じcheckoutをクラウド同期しない。Codex履歴はソースの同期手段ではない。委任の詳細は[Astra／サブエージェント運用](Codex-Astra-Workflow.md)を参照する。

### 同期

Mac／Windowsそれぞれのmain checkoutで担当範囲を編集し、push前にorigin/mainを取得して他方の変更を取り込む。衝突は内容を確認して解決し、他方の変更を取り消すforce pushは行わない。コミットの存在を両OSの実機検証完了とみなさず、実施済みgateと未確認を記録する。

Macの神経試験が終わるまでWindowsは待たない。Windowsは既存Shiu版と実測fixtureで進める。

## 2. 通信を先に作り直さない

既存Server・Clientの実コードと送受信ログを読み、`Contracts/protocol-existing.md`へ**現物どおり**記録する。ここに書くサンプルは新規提案であり、既存wireの完全な宣言ではない。

安定して維持するゲーム側の意味：

```text
Action：STOP / FORWARD / TURN_R / TURN_L / FORWARD_R / FORWARD_L
motor.forward：0〜1
motor.turn：-1〜1
入力：Latest Action Wins
出力：Latest BrainFrame Wins
sequence：セッション内で単調増加
appliedRequestId：そのstepで実際に取り込まれた入力
```

`requestedAction`は追跡情報で、Actuator入力ではない。BrainFrame.motorのみがゲームの駆動入力となる。

## 3. ShiuとMaleCNSのID・raw活動を分離する

旧Shiuの意味を持つ`DNp09_Hz`へ、MaleCNSで未同定の細胞値を入れない。

互換方針：

- `motor.forward/turn`の意味と値域は維持。
- backend識別とraw readoutは追加metadataとして設計。
- 型・左右対応を確認できたreadoutだけ、対応する生物名を表示。
- raw値が存在しない／不明なときはN/A。正常な0Hzと区別。
- Unity DTOが追加・欠落フィールドをどう扱うかfixtureでテストする。
- UI互換のために架空の脳活動を埋めない。

追加metadataの**設計例**：

```json
{
  "type": "backend_metadata",
  "contractVersion": "integration-v1",
  "backendId": "malecns_lif_poc",
  "datasetId": "male-cns:v1.0",
  "dynamicsModel": "shiu-style LIF adaptation",
  "mode": "LIVE",
  "readouts": [
    {
      "role": "forward_readout",
      "label": "NOT_VERIFIED",
      "idNamespace": "male-cns:v1.0:body",
      "bodyIds": [],
      "verified": false
    }
  ]
}
```

これは未同定状態の例であり、完成時の実測出力ではない。受信側が未知messageを安全に無視できるか確認し、対応しない場合は明示versionのadapterで導入する。

原本Serverの破壊的なschema変更は避けるが、**「Unityを絶対1行も変えずに済む」とは約束しない。** raw診断とbackend表示は修正が必要になり得る。

## 4. 時間・停止・入力所有

### 時間

次を混同しない：

- 内部積分dt。
- 1回のBrain stepで進む脳内時間（初期50ms）。
- stepの実計算時間。
- ネットワークを含むE2E。
- Unity物理時間と描画時間。

E2Eはclient送信→同じclient受信を単調時計で測る。異PCのtimestampを直接減算しない。`stepWallTimeMs`はServer自己計測、`frameAge`はClient受信からの経過とする。

### Latest Action Wins

上書きされたrequestIdはappliedされないので、そのrequestが返らないことをtimeout失敗と混同しない。latency集計は「実適用されたrequest」と「superseded」の母数を分ける。

### STOPと安全停止

- 通常STOP：脳への外部刺激をOFFにし、残留活動も測定する。
- 通信stale：Unity側のactuator inputをゼロ化。raw BrainFrameは保存。
- 緊急停止：デモを止める操作。脳の自然応答と偽らない。

元のstale timeoutは0.75秒。この値を脳内時間で測らない。新backendの遅さを隠すために無制限に伸ばさず、E2Eと欠測を表示して判断する。

同じBrain Serverへ2つの操作clientを同時接続しない。Mock ClientとUnityを同時に操作元にするとLatest Action Winsで互いの入力を消す。初期構成はactive controller1つとし、監視clientはread-onlyにする。既存Serverが未対応なら並列接続を禁止して運用する。

## 5. 神経計算の真偽を示す

合格に必要：

- 刺激対象とreadout対象が重複しない。
- Action→stimulus→network→raw rate→decoder→motorの記録がある。
- 同じraw rateを与えればAction名に依存せず同じmotorになる。
- MOCK/REPLAY/LIVE/SHIU/MALECNSを識別して保存・表示する。
- backendが途中で自動fallbackしたら明示イベントを出す。
- target ID未解決／データ欠損を正常な0Hzで隠さない。

採用N/E、zero-weight扱い、除外edgeを明記する。単に全ニューロンをオブジェクトとして保持していても、全結合が動的に有効とは限らない。

## 6. 再現用manifest

1回の検証ごとに以下を保存：

```text
runId / UTC時刻 / OS / CPU / RAM
source commit（なければsource file hash）
Unity version / Python / Brian2 / Cython / NumPy
backendId / datasetId / selectionPolicyHash / ntPolicyHash
inputDataHashes / calibrationHash
neuronCount / rawEdgeCount / effectiveEdgeCount
seed / internalDt / outputWindow
coldInit / coldCompile / warmStep median,p95,max / RSS
appliedRequestCount / supersededCount / staleCount
実施した試験／未実施の試験
```

fixtureは短い実測JSONLを使う。GB級の全spike履歴をGitへ入れない。**500 physics samples等は、独立な500試行ではない。** 統計の単位をtrialとframeで区別する。

## 7. Gitとファイル

- Unity：Assets/Packages/ProjectSettingsと.metaを管理。Library/Temp/Build/cacheは除外。[S07]
- commit／pushする前に、自分の担当外の差分が混入していないか確認。
- 大きなFBX/textureは必要ならGit LFS。LFSなしで100MB級データを通常Gitに詰めない。
- データは公式URL・version・ローカルSHA-256で再取得可能にする。
- `.env`、APIキー、PAT、ライセンス認証ファイルをcommitしない。
- 同じSceneや.blendを2人のCodexに同時編集させない。
- 既存データのpublic/private条件を勝手に変更しない。

## 8. 合流順序と中止条件

| 段階 | 合流条件 | 未達時 |
|---|---|---|
| ソース共有 | M0とW1 | Mac原本は維持、Windowsは受領不備を修正 |
| Windowsデモ | W3 | Visual制作前にローカル互換を切り分け |
| 新脳受入れ | M4/M5合格 | Shiu版でゲーム・Visualを継続 |
| LAN統合 | M6とW3/W4 | localhostで新脳、既存脳との比較に戻る |
| 本番化 | W6単体起動と表示の確認 | 合格したbackendだけ採用・正しく表示 |

物理エンジンの変更、全VNCから筋肉への直接接続、CUDA移植は別プロジェクトの判断。今回の合流条件へ追加しない。

## 9. 表示・説明の推奨文言

MaleCNS採用時：

> Google/Janelia等のMaleCNSコネクトームを利用した、仮定を明示した神経シミュレーションが運動指令を生成します。身体はUnityの物理モデルとゲーム用制御で動かしています。

Shiu採用時：

> FlyWireベースのShiu型全脳LIFモデルから、運動関連ニューロンの活動を読み出してUnityの物理ハエを操作します。

「Google公式の完全な脳エミュレーター」「実物の脳機能を完全再現」「VNCが自動で脚を直接制御」とは、実証なしに説明しない。[S01][S02][S04]

## 出典

[S01] https://male-cns.janelia.org/  
[S02] https://male-cns.janelia.org/download/  
[S04] https://github.com/philshiu/Drosophila_brain_model/blob/main/Readme.md  
[S07] https://docs.unity3d.com/es/2020.1/Manual/ExternalVersionControlSystemSupport.html  
[S11] OpenAI AGENTS.md：https://developers.openai.com/codex/guides/agents-md/
