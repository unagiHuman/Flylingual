# FlyBrain：MaleCNS検証とWindows並列開発

現在の正式プレイ画面は `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` の直接起動でBrain・Bridge・GPT Liveも自動起動し、Unityの正常・異常終了で所有サービスも終了する。従来の `Start-UnityConversation.cmd` も使用できる。[Unity起動手順](windows/Unity-Startup-Handoff.md)に、Unity 6000.5.9f1での再ビルドと正式シーン `FlylingualPlay.unity` のEditor起動をまとめた。Brain・Bridge・UnityはWindows内で動作し、通常起動にブラウザ・WebRTC・Macは不要。[Windowsローカル構成](windows/Windows-Local-Stack.md)は別のブラウザ／WebRTC構成用である。下記の初期検証計画より、現在の実行指示とAGENTS.mdを優先する。

作成日：2026-09-11（JST）／版：1.0

## 現在の統合設計の正本（2026-09-12）

Brain・GPT Live、Mac／Windowsの実行先切替、脳と言葉の双方向翻訳は
[共通設計ルール](Brain-GPTLive-CrossPlatform-Design.md)を参照する。
同文書は合意済みの設計規範であり、実装済みという意味ではない。
この下の初期検証計画と統合設計が異なる場合は、共通設計ルールを優先する。
正式リポジトリとGit運用はルートの[AGENTS.md](../AGENTS.md)に従う。
開発agentの役割分担・委任手順は[Astra／サブエージェント運用](Codex-Astra-Workflow.md)を参照する。これはゲーム内のGPT Live設定とは別である。

## 今回の決定

**MacではMaleCNSの新しい脳バックエンドを検証する。Windowsでは、現在動くShiu版を使ってUnityデモを再現し、リアルなハエVisualと発表用ビルドを作る。**

MaleCNSとMuJoCo移行を同時には行わない。物理は当面、実証済みのUnity PhysXを維持する。

| 担当 | 最初の到達点 | 次の到達点 | 触らない領域 |
|---|---|---|---|
| Mac / Codex | MaleCNSのデータ・ID・結合・メモリを確認 | 上流刺激→神経応答→motor→TCP | Unity Scene、見た目、既存Shiu環境 |
| Windows / Codex | Shiu版の脳サーバー＋UnityをWindows単体で再現 | Visual制作、HUD、操作・落下・ビルド | MaleCNSの神経探索、物理エンジン移行 |
| 共通 | 既存通信仕様を採取・固定 | Mac新脳→Windows Unityの統合 | 相手担当ファイルの無断変更 |

## 読む順番

1. 全体方針：このファイル。
2. 共同作業の境界：`03_SHARED_CONTRACT.md`。
3. Macで作業：`01_MAC_MALECNS_TEST.md`。
4. Windowsで作業：`02_WINDOWS_DEMO_VISUAL.md`。
5. 各手順書末尾の開始指示は初期検証時の記録として扱う。現在のFlylingualではルートの`AGENTS.md`を正本とし、古いテンプレートで上書きしない。

## 重要な訂正・前提

MaleCNS v1.0はGoogle Research/Janelia等が共同で構築した、**脳と腹側神経索を含む接続データ**である。完成済みの動的エミュレーターや「そのままUnityを動かせる学習済みモデル」ではない。[S01][S02]

今回作るのは、**MaleCNSの構造データに、明示した仮定のLIFダイナミクスを組み合わせる独自PoC**。Shiuの検証結果をそのままMaleCNSへ転用できたとは扱わない。

前の会話に出た「Macで動いた他のゲームの例」「約16.7万ニューロン」「約2,558万edge」は、このBrian2実装の速度・メモリの保証に使わない。ロードした集合、フィルター、モデルの種類を自分の実行で記録する。

**FlyWireの長いroot ID、上流top5、DNの意味付け、120/161/45Hzの校正値はMaleCNSへコピーしない。** 細胞型対応は同一ID対応ではない。公式関連ツールには`flywireType`等の対応情報があるが、ローカル配布表に何が含まれるかを先に検査する。[S03]

## すでにあるもの／これから作るもの

ユーザー報告を基準とする現在の実績：

- Mac：Shiu/FlyWire v783、Brian2 2.5.1、Cython 0.29.37。
- 持続ネットワーク、6 Action、実測に基づくMotorDecoder、TCP/NDJSON、Latest Action Wins。
- 50ms脳内windowのwarm計算が約180ms。Mock ClientのE2E中央値約358ms。
- Unity 6000.5.5f1、18関節の物理6脚、実Brain接続、FootPadと有限粘着の発火まで確認。
- 粘着ONの平地移動低下・yaw増加は未解決。段差5cmや落下バランスは完成とはしない。
- Windowsで同じ一式が動作した実績、MaleCNSバックエンドの動作実績はまだない。

この手順書作成時、ユーザーのMac/Windowsのローカルファイルを直接読んだり実行したりはしていない。パス・成果は会話の報告を使用し、**Codexが最初に現物確認する**。

## 作業ディレクトリ

既存の動作済み環境は残す。

```text
Mac：/Users/isaoohta/UnityGame/FlyBrain/
├─ Work/
│  ├─ Drosophila_brain_model/        # 元の成功環境：保護
│  └─ FlyBrainUnityPoC/              # 元の成功環境：保護
├─ Parallel/                         # 今回新設する共有コードのルート
│  ├─ Brain/
│  │  ├─ ShiuBaseline/               # 成功環境のソースsnapshot
│  │  └─ MaleCNS/                    # Mac担当の新規実装
│  ├─ UnityProject/                  # Windows担当のUnity snapshot
│  ├─ Contracts/
│  ├─ VisualSource/                  # .blendなど。Unity Assetsの外
│  ├─ Docs/
│  └─ artifacts/                     # ログ等。原則Git除外
└─ Data/malecns/v1.0/                # 大容量データ。Gitに入れない
```

Windowsの作業先は**新規提案**として`C:\Dev\FlyBrain\Parallel`とする。既存のWindows作業パスがある場合はその場所へ読み替える。原本へ上書きしない。

## 接続の進め方

```text
段階1：各PCで独立
Mac       MaleCNSデータ／神経PoC
Windows   Shiu Brain → Unity → Visual

段階2：Mac内で新脳を検証
Mac       MaleCNS Brain → Mock Client
          → 必要な場合だけMac Unity

段階3：2台を接続
Mac       MaleCNS Brain Server
                    ↓ 信頼できるローカルネットワーク
Windows   Unity＋リアルVisual

段階4：本番構成
Windows   採用したBrain Server＋Unityを1台で起動
```

Macは8765のShiu版を残し、新MaleCNSサーバーを8766に分ける。これは本手順の割り当てであり、既存コードに新CLIが実装済みという意味ではない。

## 完了判定

「データがロードできた」と「運動関連readoutが使える」は別に判定する。MaleCNSの採用条件は以下。

- ID・結合・神経伝達物質の扱いが記録されている。
- 刺激対象と観測対象が重複せず、上流刺激から観測活動が変わる。
- 同じネットワークで入力切り替えを処理できる。
- raw活動からmotorを生成し、Action名から出力を捏造しない。
- メモリ・p95計算時間・E2Eを測定している。
- Unityのstale安全停止とデータセット名表示が正しい。
- 未達ならShiu版へ戻せる。MaleCNSが動いたふりはしない。

## 同梱スクリプト

`environment_probe.py`：環境記録。秘密情報を含む環境変数全体は出力しない。

`download_malecns.py`：公式配布ページから必要な3ファイルだけを解決・取得する。最初は小さい2ファイルだけ。ローカルSHA-256を保存する。

`inspect_feather.py`：Feather v2のschemaと少数行を確認する。神経系や巨大な行列は作らない。

**同梱したのは準備用スクリプトであり、MaleCNSシミュレーターそのものではない。** 新バックエンドは手順書に従ってCodexが既存実装を確認した上で作成する。スクリプトのテスト範囲は`VALIDATION.md`を参照。

## ハッカソンとの区別

これは技術検証・共同開発用の手順。事前コード、設計書、外部アセットの持込可否はイベントの最新の正式ルールを別途確認する。**別フォルダーに置くだけで持込が適法・適格になるとは判断しない。** 本書はハッカソンの参加規則を再確認したものではない。

## 出典

[S01] MaleCNS公式概要：https://male-cns.janelia.org/

[S02] MaleCNS公式配布：https://male-cns.janelia.org/download/

[S03] 研究チーム関連のnatverse/malecns：https://natverse.org/malecns/

全資料は`SOURCES.md`に集約。
