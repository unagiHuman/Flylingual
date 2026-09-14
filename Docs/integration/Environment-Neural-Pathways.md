# 環境イベントから神経入力への経路候補

2026-09-14。[前段の候補監査](Affective-Candidate-Audit.md)から進め、一次研究での機能とMaleCNS v1.0の実ID・現行CSR接続を照合した。今回の範囲は経路特定であり、刺激・神経伝播・ゲーム動作の受入れではない。

## 危険の視覚入力: 検証候補を特定

`ハエたたきの接近 → LC4 / LPLC2 → DNp01（GF）` を最初の検証候補とする。LC4とLPLC2からGFへの直接入力、接近物体の角速度・角サイズに関する役割は成虫の原著で報告されている。原著はMaleCNS個体そのものの生理測定ではなく、型の機能を対応させる根拠である。[Ache et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30827912/)

| 役割 | MaleCNS exact type | 個体数 | 現行CSRでDNp01への直接edge |
|---|---|---:|---:|
| 入力候補 | LC4 | 126（somaSide L=71/R=55） | 126 |
| 入力候補 | LPLC2 | 185（L=94/R=91） | 185 |
| 下流観測候補 | DNp01 | 2 | 対象bodyIdは下記 |

観測候補はDNp01 `10001`（somaSide R）と `10010`（somaSide L）。ローカルのsynonymsに `Kennedy and Broadie 2018: GF` があり、exact type `GF` という別集合を作らない。左右は注釈のsomaSideで、刺激視野の側と同一だとは仮定しない。

例としてLC4 `12032 → 10010` はweight `1.705`、LPLC2 `11498 → 10010` は `0.055`。確認した311 edgeは全て正で、数値は既存checkpointのweight単位である。シナプス数・Hz・生理的刺激強度に読み替えない。全LC4/LPLC2を一括発火させる刺激条件を、この個体数から自動決定しない。

公式の個体別NTファイルを取得し、LC4の126、LPLC2の185、DNp01の2細胞すべての `consensus_nt=acetylcholine` を確認した。これは配布注釈による同定で、生理実験による個体別確証ではない。少なくとも、dopamine出力の除外によって最初の伝達が途切れる候補とは異なり、現行CSR内に入力と下流観測点を結ぶ有効edgeが存在する。

LC6/LC16からDNp01への直接edgeは今回0、LPLC1は1だった。機能の名前が近いという理由で最初の入力集合へ追加しない。

LC4/LPLC2/DNp01の全IDと、既存Action用F/R/L入力IDとの交差は空だった。これは直接刺激の重複がないという確認で、下流の神経経路やmotorへの非干渉を保証しない。

## 甘味入力: 型と味質の対応が未同定

候補を全gustatoryから、口器のlabellar bristle型（LB1a–e、LB2a–d、LB3/3a–d、LB4a–b）などへ細分化した。ただしローカル注釈ではこれらのreceptorTypeは未注釈で、どの集合を甘味入力として採用するかは確定していない。脚・翅のputative_ppk/IR注釈を甘味と置き換えない。

MaleCNS味覚回路を扱うTastekin et al.の正式論文は分子同定と回路対応を報告しているが、取得できた公式abstractにはLB型別の味質対応表がない。正式版DOI `10.1016/j.cell.2026.08.016`、2026-09-03、元プレプリントDOI `10.1101/2025.08.25.671814`。正式本文は取得エラー、プレプリント本文はアクセス制限で取得できず、公開著者補足からも対応表を確認できなかった。未読の表に基づく推定はしない。[Janelia公式論文情報](https://www.janelia.org/publication/the-complete-gustatory-connectome-of-adult-drosophila-reveals-how-taste-guides-feeding)

甘味側で次に必要なのは、この論文のMaleCNS型→味質対応表または同等の一次データである。旧GAL4-LB1とMaleCNSのLB1型は名前だけで一致させず、FlyWireの神経IDも流用しない。ここが未確定でも、上記の視覚危険経路の検証準備は独立して進められる。

## 環境との接続で残る条件

現在の `threat_started` はidleタイマーに基づく警告開始で、ハエの視野内で測定した角サイズ・角速度ではない。`BlindSugarRunIdleSwatter` は警告中のハエたたき位置を計算するが、それを視覚入力へ変換する処理は未実装である。

次の実装では、ハエ基準の接近物体の位置・大きさ・接近変化を観測し、視覚特徴から刺激への対応と強度・時間を明示する。単なる警告ONを代用する場合は「環境イベントによる実験的刺激」と表示し、生物学的な視覚再現とは呼ばない。いずれの場合も、刺激されたLC4/LPLC2自身の発火と、独立したDNp01の応答を分離して保存する。

`threat_ended` と `threat_cancelled` はともに入力終了を要求するが、前者だけが実移動による警告解除である。解除後の神経活動低下や残留は測定値として扱い、終了イベントから「安心」「負の強化」を生成しない。`fall` と `swatted` は接近視覚と異なる事象であり、苦味GRNやPPL1へ同じ信号を送る根拠にはしない。

実刺激を加えると、既存神経結合を通じてmotorにも影響し得る。速度ボーナス・固定motorは追加しないが、「神経刺激しても数値が完全に不変」とは約束しない。まず実Brainで下流応答、刺激終了、通常STOPと緊急停止、失効・接続世代変更を分けて検証する。Unityへの有効化はその後とする。

## 報酬・嫌悪readoutへの接続

PAM/PPL1の有効出力が0でも、他の細胞からPAM/PPL1への入力まで0とは限らない。今回、味覚・視覚候補から中継1細胞を経由してPAM/PPL1へ到達する有効経路を確認した。ただし正負の組合せが混在し、接続の存在だけで発火・報酬・嫌悪を判定できない。

例: `LB2a 77868 → AstA1 10035 → PPL102 13428` は正／負。これは糖による正の報酬経路という証拠ではない。現行fast-synapse LIFにおけるAstA1の負のweightと、AstAペプチドの神経修飾作用も同一視しない。

したがって、最初の危険経路の観測はDNp01のraw応答とし、PAM/PPL1由来のaffectiveProxyは引き続き未設定とする。出力のないPAM/PPL1を直接刺激し、その細胞自身の発火を報酬の証明として返す方法は採用しない。

## 再現・未検証

`tools/audit_environment_paths.py` は実注釈とmmap CSRを使い、直接edgeと最大2hopを調べる。直接LC4/LPLC2→DNp01の全edge、入力と観測の実ID、個体別NT、既存Action入力との交差をJSONへ保存する。2hopには中継10,000・読取5,000,000 edgeの上限を設け、打切時は未探索部分の経路不存在を主張しない。全graphの網羅探索やLIF試行は行わない。

注釈SHA-256=`2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2`。今回取得したNTファイルは43,282,834 bytes、SHA-256=`95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621`で、既存download manifestに一致した。publisher checksumの独立検証とは区別する。[公式配布](https://male-cns.janelia.org/download/)

Brain runtime、NT policy、decoder、Unityの変更はない。`ready=false`、`neuralInputApplied=false`、affectiveProxy未設定を維持する。

再現コマンド（repo rootから）:

```powershell
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/audit_environment_paths.py --output artifacts/neural-feedback/environment-path-audit-reproduced.json
```

Python 3.10.12 / NumPy 1.24.3 / PyArrow 24.0.0。親の実行で約3.14秒、2,760,778格納edgeを読取り、全て非ゼロだった。中継候補24,311のうち10,000で打切。最初の局所監査の全直接／探索範囲内2hop件数を再現した。上限100 edge／中継0、ゼロweight除外、正負保持、非有限weight・範囲外target拒否も監査CLIの制約検査として確認した。これらは実Brain刺激試験の代替ではない。

原本は `artifacts/neural-feedback/environment-path-audit.json`、再現CLI出力は上記JSON。初回はDNp01へのdirect edgeを追加の局所読みで確認したため累計読取2,916,649 edge、再現CLIは既読行を共有するため2,760,778 edgeとなる。格納edge総数と探索中の非ゼロedge数を区別する。生成JSONと43MBのNTファイルはGit除外のまま管理する。
