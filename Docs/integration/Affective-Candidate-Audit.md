# 環境からの神経入力候補監査

2026-09-14。環境イベントの実装後、実際のMaleCNS神経入力へ進めるために、ローカルの実注釈と現行LIF用CSRを照合した。**候補監査は完了したが、報酬・嫌悪入力の有効化条件は満たしていない。** ゲーム内では引き続き `neuralInputApplied=false`、`affectiveProxy.status=not_configured` とする。

後続の[環境→神経経路の照合](Environment-Neural-Pathways.md)では、公式の個体別NT表を取得し、LC4/LPLC2→DNp01の有効な直接接続を確認した。以下のNT未確認・未配置は初回監査時点の記録であり、後続結果と区別する。甘味入力の型対応と刺激条件は依然未確定である。

## 実データの結果

| 注釈で選んだ候補 | 細胞数 | 現行graph内 | 有効出力edgeがある細胞数 |
|---|---:|---:|---:|
| PAM01–15 | 316 | 316 | 0 |
| PPL101–108 | 16 | 16 | 0 |
| Sugar関連synonym | 6 | 6 | 0 |
| Bitter-SEL synonym | 4 | 4 | 0 |
| class=gustatory | 1,428 | 1,428 | 1,134 |

PAM10の代表bodyIdは28434、29565、32865。PPL101は11327、11900。Sugar関連はGNG540（11740、15214）、GNG056（14100、14254）、GNG550（15487、17369）。Bitter-SELはDNg28（11442、11756、383627、451851712）。これらは検索候補であり、刺激対象として採用したIDではない。

gustatory集合の有効出力edgeは86,037、全て正の重みだった。しかしreceptorTypeは未注釈677、putative_ppk25が257、putative_ppk23が269、putative_IR52bが225で、集合全体を甘味受容細胞とは確定できない。正の重みも、甘味・報酬という機能の証拠にはならない。

現行graphは166,700細胞、格納edge数19,670,694。候補行については非ゼロweightだけを有効edgeと数えた。上記の出力edgeゼロは**このモデルでの動的出力がない**という意味で、解剖学的結合が存在しないという意味ではない。個体別NTの別featherはローカルに未配置で、注釈表にNT列はない。型名や重み符号から個体別consensus_ntを補完していない。

## 入力を有効化しない理由

現行 `nt_policy_exploratory_lif_v1.json` はdopamineをfast synapseから除外する。`lif_kernels.py` には固定重みを伝えるLIF更新と外部刺激があるが、dopamine受容体・神経修飾・報酬学習による重み更新は実装されていない。出力edgeがない細胞を直接発火させ、その発火だけを「報酬反応」として読み戻す方法は、回路を介した神経反応の検証にならない。

またPAMを一括して「増加＝報酬」と定義しない。糖報酬に関わるPAMの部分集合が報告される一方、PAM-γ3では糖摂取時の活動抑制が報酬に関係し、その活性化は嫌悪記憶を誘導するという結果がある。これをMaleCNSの個別型・個別IDに適用するには対応の確認が必要である。[Liu et al., 2012](https://www.nature.com/articles/nature11304)、[Yamagata et al., 2016](https://pubmed.ncbi.nlm.nih.gov/27997541/)

ハエたたきからの離脱は現状では危険イベントの終了として扱う。罰の省略を報酬として符号化する研究は反転学習の条件で行われており、ゲームで警告が終了した事実だけから負の強化・学習が成立したとは判定しない。[原著](https://www.nature.com/articles/s41467-021-21388-w)

## 次の実装条件

1. 味覚・危険刺激それぞれについて、成虫の一次研究とMaleCNS型対応から入力候補を絞る。全gustatory集合や全PAM集合の一括刺激を採用しない。
2. 個体別NTと構造結合を照合し、現在の動的graphに経路が残るか確認する。神経修飾が必要なら、現行fast-synapse LIFとは別のモデル変更として仮定と検証範囲を定義する。
3. 刺激を受ける細胞と独立した観測集合を定義し、直接刺激分・下流応答を分離する。刺激条件とbaseline・校正基準を記録する。
4. 環境イベントのscope・鮮度・重複排除をBrainまで接続する。キャンセルと実際の回避を区別する。既存motor値の直接変更やゲーム能力のボーナスは加えない。
5. Windows実Brainで刺激前後と停止・失効を検証する。観測値から主観的感情を確定せず、readyや履歴効果を未検証のまま昇格しない。

## 再現と証拠

`tools/audit_affective_candidates.py` は注釈とmmap CSRの候補行を読む監査用CLIで、BrainやUnityを起動しない。生成JSONは `artifacts/neural-feedback/affective-candidate-audit.json`。注釈14,483,314 bytes、211,577行、SHA-256=`2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` は既存download manifestと一致する。publisher checksumの独立検証とは区別する。[公式配布](https://male-cns.janelia.org/download/)

CSRのbodyIds SHA-256=`ab90597b7b0ce07cbc22cb39a65b70bea2ac73cc7fd225951bd9d73f2fc8dd3f`、indptr SHA-256=`0b466606b702ac097daffd3b46eea8a75851470b9c8624f7d63df1a1d8014923`。全weightsの再hashやGB級構造表の読取は行っていないため、今回の監査だけで全graph内容の同一性を再証明したとはしない。

これは実データの静的監査であり、実Brain刺激試験やゲーム動作試験ではない。Unity、Brain runtime、数値設定は変更していない。

再現コマンド（repo rootから）:

```powershell
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/audit_affective_candidates.py --output artifacts/neural-feedback/affective-candidate-audit-reproduced.json
```

Python 3.10.12、NumPy 1.24.3、PyArrow 24.0.0で実行し、5集合・1,770候補・候補edge計86,037を再現した。親の最終実行は約3.24秒。これはCLI経過時間で、神経計算時間やE2Eの計測ではない。再現JSONに実行引数・依存版・hash・個別候補を保存する。生成データをGitに含めず、CLIとこの要約を管理する。
