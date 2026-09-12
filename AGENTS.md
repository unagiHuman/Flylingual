# Flylingual — Astra 開発ルール

## Goal

MaleCNSの独立検証と、Windows上のUnityデモ／リアルVisualを並列で進める。
正式な作業対象リポジトリはこのFlylingualのみとする。隣接するFlytestは参照・実行・編集・コミット・プッシュの対象にしない。
Docs/00_START_HERE.mdを入口とし、作業に関係する正本・直接依存先を読む。初期OS手順書の歴史的コマンドを現在の実行許可とみなさない。
Brain・GPT Live・接続先切替・双方向翻訳の作業前には、設計ルールの正本 `Docs/Brain-GPTLive-CrossPlatform-Design.md` を読む。同文書を統合設計について旧手順書より優先し、規範の確定と実装・実測の完了を区別する。

## Astraと委任

- 主担当はGPT-6 Astraを想定し、要求解釈・設計判断・科学的判断・安全境界・統合・最終レビューを担う。これは開発運用の規範であり、Codex実行モデルやゲームのGPT Liveモデルを変更する設定ではない。
- 最新依頼から完了条件を定め、通常の可逆的判断は既存仕様に沿って進める。調査・設計のみの依頼から実装へ広げず、重要な未確定分岐・追加権限が必要な部分だけ確認する。
- 独立した具体的な下位作業があり、親も別の有用な作業を並行できる場合はサブエージェントへ委任する。特に仕様確定済みの文書執筆は軽量モデルを使う。短い回答・単純pull・単一の小変更では委任を必須にしない。
- 委任前に `Docs/Codex-Astra-Workflow.md` を読み、モデル選択・許可ファイル・完了条件を明示する。環境で禁止・未提供の場合は親が続行し、委任のために作業を止めない。
- 編集対象は1ファイル1担当。Unity Editor・Brain process・TCP controller・計測・Git indexを複数agentから同時操作しない。子の成果は親が差分と必要な生の証拠を確認し、commit／pushを一元化する。

## Ownership

- Mac: Brain/MaleCNS、Docs/mac、共通Bridge・双方向翻訳・接続先切替・共通設定／起動管理。開発OSと実行OSを分離し、同じ実装を両OSで使用する。
- Windows: Unityゲーム／Visual／HUD、音声Adapter、接続先選択UI、出力抑止、VisualSource、Docs/windows。担当外の同時編集を避ける。
- Brain/ShiuBaselineは成功baseline。Windowsのpath/compile互換以外を変更しない。
- Contractsは初版Mac。以後、単独の統合担当が変更する。
- 既存PhysicsRig、CPG、joint、FootPad、摩擦、Brain MotorDecoderを無断変更しない。

## Science and provenance

- MaleCNSはデータセットであり、完成した脳エミュレーターではない。
- FlyWire root ID、top5、校正値をMaleCNSへ流用しない。
- ID、NT policy、細胞型対応、集合除外、N/E、seed、dtを記録する。
- 未同定の細胞をDNa02/DNp09と呼ばない。
- Actionからmotorを直接生成しない。raw神経出力を経由する。
- LIVE、REPLAY、MOCK、SHIU、MALECNSを明示する。
- 全CNS、動的に有効なedge、subgraphを区別する。

## Engineering

- 両OSで別checkoutを使い、mainへ直接コミット・プッシュする。親がtask範囲だけをstageし、push前にorigin/mainを取得して他方の変更を確認・保持する。force pushは行わない。旧文書の機能別ブランチ方針は適用しない。
- 手順書の例CLIが既存実装にあると仮定しない。--helpとソースを読む。
- Mac原本 /Users/isaoohta/UnityGame/FlyBrain/Work は保護する。
- 巨大なdense行列やPython edgeオブジェクト配列を作らない。
- 試験は段階別。予算外の総当たり・大量trial・GPU化を始めない。
- 変更前後で機構、数値、設定を同時に変えない。
- Unity physicsは引き続きPhysX。MuJoCo移行をこの作業へ追加しない。
- APIキー、PAT、ライセンス秘密情報、GB級データ、生成cacheをcommitしない。
- サーバーはlocalhost。LAN公開は明示した信頼できる接続に限定する。
- 成功していない試験を成功扱いにしない。目視未実施はそのまま報告する。

## 検証と報告

- 文書だけの変更は正本との整合・参照先・diffを確認し、Unity起動・神経試験・課金API呼び出しをしない。コードは影響する挙動を検証し、変更・失敗・未解決の懸念がなければ検証範囲を広げたり繰り返したりしない。
- 必須の試行数、独立seed、観測時間、実Brain／実API／Windows Unityのgateは省略しない。compile、TCP到達、機能、操作感の成功を区別し、未検証のreadyを昇格しない。
- 日本語で結果を先に簡潔に報告する。変更ファイル・実施した検証・未確認・commitを示し、定義ファイルを編集した場合は明記する。コード全文は貼らない。
- Brain／統合の実測では実行コマンド、source/data/config hash、依存版、測定母数、RSS、計算時間、E2E、次のgateを記録する。文書のみの変更に無関係な数値欄を要求しない。
