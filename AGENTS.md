# FlyBrain Parallel Development

## Goal
MaleCNSの独立検証と、Windows上のUnityデモ／リアルVisualを並列で進める。
正式な作業対象リポジトリはこのFlylingualのみとする。隣接するFlytestは参照・実行・編集・コミット・プッシュの対象にしない。
まずDocs/00_START_HERE.md、Docs/03_SHARED_CONTRACT.md、自分のOS担当手順書を読む。
Brain・GPT Live・接続先切替・双方向翻訳の作業前には、設計ルールの正本 `Docs/Brain-GPTLive-CrossPlatform-Design.md` を読む。同文書を統合設計について旧手順書より優先し、規範の確定と実装・実測の完了を区別する。

## Ownership
- Mac: Brain/MaleCNS、Docs/mac。
- Mac: 共通Bridge・脳と言葉の双方向翻訳・Brain接続先切替・共通設定／起動管理も担当する。開発OSと実行OSを分離し、同じ実装をMac／Windowsで使用する。
- Windows: UnityProjectのVisualDemo/HUD/デモ、VisualSource、Docs/windows。
- Windows: Unity側の接続先選択UI・音声Adapter・出力抑止を担当する。Bridge配置、切替手順、操作権、安全境界は上記正本に従い、担当外の同時編集を避ける。
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
- ユーザー指示（2026-09-12）：今後は作業ブランチを分けず、mainへ直接コミット・プッシュする。既存文書の機能別ブランチ方針よりこの指示を優先する。プッシュ前にorigin/mainを取得して差分を確認し、他の変更を取り消すforce pushは行わない。
- 手順書の例CLIが既存実装にあると仮定しない。--helpとソースを読む。
- Mac原本 /Users/isaoohta/UnityGame/FlyBrain/Work は保護する。
- 巨大なdense行列やPython edgeオブジェクト配列を作らない。
- 試験は段階別。予算外の総当たり・大量trial・GPU化を始めない。
- 変更前後で機構、数値、設定を同時に変えない。
- Unity physicsは引き続きPhysX。MuJoCo移行をこの作業へ追加しない。
- APIキー、PAT、ライセンス秘密情報、GB級データ、生成cacheをcommitしない。
- サーバーはlocalhost。LAN公開は明示した信頼できる接続に限定する。
- 成功していない試験を成功扱いにしない。目視未実施はそのまま報告する。

## Deliverables
実行コマンド、変更ファイル、source hash、data hash、依存版、測定母数、
RSS、計算時間、E2E、実施／未実施、次のGateを報告する。
