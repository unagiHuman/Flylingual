# FlyBrain Parallel Development

## Goal
MaleCNSの独立検証と、Windows上のUnityデモ／リアルVisualを並列で進める。
まずDocs/00_START_HERE.md、Docs/03_SHARED_CONTRACT.md、自分のOS担当手順書を読む。

## Ownership
- Mac: Brain/MaleCNS、Docs/mac。
- Windows: UnityProjectのVisualDemo/HUD/デモ、VisualSource、Docs/windows。
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
