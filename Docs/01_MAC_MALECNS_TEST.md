# Mac手順書：MaleCNSバックエンド検証

版1.0／2026-09-11 JST

## 0. 目的と今回やらないこと

目的は、Google/Janelia等のMaleCNS v1.0データをMacで扱い、明示したLIFモデルで入力依存の神経応答を検証し、既存のゲーム向けmotorインターフェースへ接続すること。[S01][S02]

最初からVNCの全運動ニューロンで18関節を直接駆動しない。最初の接続は従来どおり高レベルの`forward/turn`とする。**VNCのニューロンをロードしただけでは、VNCが行動生成に寄与したことにはならない。**

Shiu版、Unity物理、粘着、リアルVisual、MuJoCo移行はこの担当の作業対象外。過去のSugar実験や同じ30 trialは繰り返さない。

### 作業の段階

| Gate | 内容 | 合格証拠 |
|---|---|---|
| M0 | 元環境保存、共同作業の準備 | baseline manifest、Windows引渡し資料 |
| M1 | 独立Python環境 | package一覧、Cython最小テスト |
| M2 | 公式データ取得・schema監査 | download manifest、schema JSON |
| M3 | 対象集合・疎結合の確定 | 実測N/E、除外表、NT policy、RSS見積り |
| M4 | ニューロン同定と短いLIF試験 | ID出典、上流刺激→別ニューロン応答 |
| M5 | persistent化、motor校正、速度 | holdout評価、window/p95/RSS |
| M6 | 既存契約に接続 | 8766のサーバー、backend表示、E2E |

Gateを飛ばさない。M0完了時点でWindowsは作業開始できる。

---

## M0. 元の成功環境を残し、Windowsへ渡す

### M0-1. 実パスの確認

まず手順パックを`/Users/isaoohta/UnityGame/FlyBrain/Guides/FlyBrain_Parallel_Test_Guide/`へ展開する。異なる場所へ展開した場合はGUIDEを変更する。Mac Terminalで実行する。

```bash
GUIDE="/Users/isaoohta/UnityGame/FlyBrain/Guides/FlyBrain_Parallel_Test_Guide"
test -f "$GUIDE/00_START_HERE.md" || { echo "手順パックの展開先を確認"; exit 1; }
ROOT="/Users/isaoohta/UnityGame/FlyBrain"
OLD_BRAIN="$ROOT/Work/Drosophila_brain_model"
OLD_UNITY="$ROOT/Work/FlyBrainUnityPoC"
NEW="$ROOT/Parallel"

test -f "$OLD_BRAIN/brain_server.py" || { echo "brain_server.pyがない"; exit 1; }
test -f "$OLD_UNITY/ProjectSettings/ProjectVersion.txt" || { echo "Unity projectがない"; exit 1; }
cat "$OLD_UNITY/ProjectSettings/ProjectVersion.txt"
```

Unity Editorは保存して終了してからsnapshotを作る。既存Pythonサーバーが結果を書いている最中のフォルダーをそのまま複製しない。

### M0-2. 共有コードの新しいコピーを作る

**`Parallel`が未作成のときだけ**次を実行する。すでに存在する場合は上書きせず、Codexに中身と差分を確認させる。

```bash
if [ -e "$NEW" ]; then
  echo "Parallelはすでに存在します。上書きせず差分を確認してください。"
  exit 1
fi
mkdir -p "$NEW/Brain/ShiuBaseline" "$NEW/Brain/MaleCNS" \
  "$NEW/UnityProject" "$NEW/Contracts/fixtures" "$NEW/Docs" \
  "$NEW/VisualSource" "$NEW/artifacts"

rsync -a \
  --exclude='.git/' --exclude='__pycache__/' --exclude='.venv/' \
  --exclude='results/' --exclude='Logs/' --exclude='Build/' \
  --exclude='cache/' --exclude='.cache/' --exclude='cython_cache/' \
  "$OLD_BRAIN/" "$NEW/Brain/ShiuBaseline/"

# .metaを含む。Library/Temp/Build等は移さない。
rsync -a "$OLD_UNITY/Assets/" "$NEW/UnityProject/Assets/"
rsync -a "$OLD_UNITY/Packages/" "$NEW/UnityProject/Packages/"
rsync -a "$OLD_UNITY/ProjectSettings/" "$NEW/UnityProject/ProjectSettings/"
```

これはソースsnapshotであり、全ディスクバックアップではない。`results`から必要な以下だけを別途移す。

- 現在のMotorDecoderが実際に読む校正JSON。**結果フォルダーにあるからと除外したままにしない。**
- 既存の6 Actionを含む小さいBrainFrame記録と通信実例。
- `README_brain_server.md`、実行引数、モデルデータのファイル一覧。
- 現在の動作に必要な設定ファイル。絶対パス依存を列挙する。

Codexは`poc_config.py`と`brain_controller.py`を読み、データ・校正・cacheの実際の解決先を検査する。新コピー側だけを相対パスまたは設定パスで起動できるようにする。原本を変更しない。

Unityの共有では`Assets`、`Packages`、`ProjectSettings`と`.meta`が重要であり、`Library`はローカル再生成する。[S07]

### M0-3. Gitと引渡し

このPoCにはGitがなかったとの報告がある。新コピーで初めて履歴を作る。`templates/gitignore.txt`を`.gitignore`、`templates/gitattributes.txt`を`.gitattributes`、`templates/AGENTS.md`を`AGENTS.md`として配置する。

```bash
cp "$GUIDE/templates/gitignore.txt" "$NEW/.gitignore"
cp "$GUIDE/templates/gitattributes.txt" "$NEW/.gitattributes"
cp "$GUIDE/templates/AGENTS.md" "$NEW/AGENTS.md"
cp "$GUIDE/00_START_HERE.md" "$GUIDE/01_MAC_MALECNS_TEST.md" \
  "$GUIDE/02_WINDOWS_DEMO_VISUAL.md" "$GUIDE/03_SHARED_CONTRACT.md" \
  "$GUIDE/SOURCES.md" "$NEW/Docs/"
cd "$NEW"
git init -b main
git status --short
# 以下のgit add前に大容量データ・APIキー・cache・ライセンス秘密情報がないか確認する。
git add .gitignore .gitattributes AGENTS.md Brain UnityProject Contracts Docs VisualSource
git diff --cached --stat
git status --short
# 内容確認後だけ実行する。
git commit -m "Preserve working Shiu and Unity source baseline"
git tag baseline-shiu-physx-source
```

外部公開は不要。ユーザーが指定したprivate GitHubリポジトリへpushするか、このsnapshotをアーカイブでWindowsへ渡す。**GitHubへの作成・upload・公開はこの手順書の作成だけでは実施していない。** 認証トークンはURLへ埋め込まない。

大容量のShiuデータはGit除外のまま、別のデータアーカイブとSHA-256 manifestで渡す。Mac固有のconda環境、Cython生成物、`.dylib`、`Library`は渡さない。

`Contracts/`の最初の作成者はMac側とし、Windows担当はそのcommitを基準に作業を始める。その後の契約変更は同時編集しない。

---

## M1. 成功したPython環境を複製する

### M1-1. 手順パックの配置

このZIPを、例えば次へ展開する。

```text
/Users/isaoohta/UnityGame/FlyBrain/Guides/FlyBrain_Parallel_Test_Guide/
```

以下ではこの場所を使う。実際の展開先に合わせて一度だけ変更する。

```bash
GUIDE="/Users/isaoohta/UnityGame/FlyBrain/Guides/FlyBrain_Parallel_Test_Guide"
ROOT="/Users/isaoohta/UnityGame/FlyBrain"
NEW="$ROOT/Parallel"
DATA="$ROOT/Data/malecns/v1.0"
mkdir -p "$NEW/artifacts/env" "$DATA"

source /Users/isaoohta/miniforge3/etc/profile.d/conda.sh
conda activate brian2
python "$GUIDE/scripts/environment_probe.py" \
  --unity-project "$ROOT/Work/FlyBrainUnityPoC" \
  --output "$NEW/artifacts/env/mac_shiu_baseline.json"
conda env export > "$NEW/artifacts/env/mac_shiu_full.yml"
conda env export --no-builds > "$NEW/artifacts/env/mac_shiu_no_builds.yml"
conda env export --from-history > "$NEW/artifacts/env/mac_shiu_from_history.yml"
python -m pip freeze > "$NEW/artifacts/env/mac_shiu_pip_freeze.txt"
```

**`--no-builds`でもOS固有packageが残り得るため、このYAMLをそのままWindowsへ適用しない。** Windows用の必要依存だけを整理する。[S06]

### M1-2. 新環境

```bash
conda env list
# flybrain-malecnsが未作成のときだけ実行する。
conda create -n flybrain-malecns --clone brian2
conda activate flybrain-malecns

python "$GUIDE/scripts/environment_probe.py" \
  --output "$NEW/artifacts/env/mac_malecns_environment.json"
python -c "import brian2, Cython, numpy, pyarrow; print(brian2.__version__, Cython.__version__, numpy.__version__, pyarrow.__version__)"
```

報告済みの基準はBrian2 2.5.1、Cython 0.29.37、Python 3.10。NumPy等は**上の実測一覧を正**とする。無差別upgradeはしない。別環境の利用はBrian2も推奨している。[S05]

Macのチップ・RAMはこの手順では未確定なので、probeとActivity Monitorで確認する。既存の実行成功はMaleCNSのRSS・速度を保証しない。

### M1-3. Cythonの最小確認

```bash
mkdir -p "$NEW/artifacts/cache/malecns-cython"
export FLYBRAIN_CYTHON_CACHE="$NEW/artifacts/cache/malecns-cython"
CC=/usr/bin/clang CXX=/usr/bin/clang++ python - <<'PY'
import os
from brian2 import NeuronGroup, Network, ms, prefs
prefs.codegen.target = 'cython'
prefs.codegen.runtime.cython.cache_dir = os.environ['FLYBRAIN_CYTHON_CACHE']
g = NeuronGroup(1, 'dv/dt = -v/(10*ms) : 1', method='euler')
Network(g).run(1*ms)
print('Cython minimal test: PASS')
PY
```

エラー時は原因を保存し、NumPyへ黙ってfallbackして成功扱いにしない。上記プログラムは最小コンパイル確認用で、MaleCNSの神経モデルではない。

---

## M2. 必要な公式データだけを取得する

必要なファイルは3つ。[S02]

| ファイル | 公式ページの記載サイズ | 用途 |
|---|---:|---|
| body-annotations-male-cns-v1.0-minconf-0.5.feather | 13MB | 細胞型、左右、クラス等 |
| body-neurotransmitters-male-cns-v1.0.feather | 42MB | ニューロン単位の伝達物質予測 |
| connectome-weights-male-cns-v1.0-minconf-0.5.feather | 1.1GB | segment間の接続強度 |

EM画像、全skeleton、syn-points、syn-partners、Neo4j DBは今回は取得しない。公式接続表は**全segmentの表**であり、「行に出るIDがすべて採用するニューロン」とは限らない。[S02]

### M2-1. 小さいannotation/NT表を先に取得

```bash
python "$GUIDE/scripts/download_malecns.py" --out "$DATA" --only metadata --dry-run
python "$GUIDE/scripts/download_malecns.py" --out "$DATA" --only metadata
python "$GUIDE/scripts/inspect_feather.py" \
  "$DATA/body-annotations-male-cns-v1.0-minconf-0.5.feather" \
  "$DATA/body-neurotransmitters-male-cns-v1.0.feather" \
  --output "$NEW/artifacts/malecns_metadata_schema.json"
```

取得スクリプトは公式ページに現在掲載されているリンクを探す。リンクがなくなった場合は停止する。似た名前のURLを想像で補わない。SHA-256は手元で計算した再現用ハッシュであり、公開元署名を検証した意味ではない。

### M2-2. 実schemaを確認する

Codexは次を実ファイルから確認し、`Brain/MaleCNS/config/schema_map.json`を作る。

- ニューロンID列または保存indexの位置とdtype。
- cell type、instance、side、class、status、cross-dataset type対応の有無。
- NT表のID、予測カテゴリ、確率・信頼度、同じIDに複数行があるか。
- `null`、空文字、カテゴリー型、リスト列の扱い。

`bodyId`、`body`、`root_id`等の名前を先に決め打ちしない。Featherのpandas index情報も確認する。**IDをfloatへ変換しない。** 内部は整数、JSON境界では文字列で保持する。

### M2-3. 結合表を取得

ディスクに余裕があることを確認する。本手順ではデータ変換・cacheを含む作業用に20GB程度の空き確保を勧めるが、これは公式の必要容量ではなく作業予算である。

```bash
python "$GUIDE/scripts/download_malecns.py" --out "$DATA" --only all
python "$GUIDE/scripts/inspect_feather.py" \
  "$DATA/connectome-weights-male-cns-v1.0-minconf-0.5.feather" \
  --sample-rows 3 \
  --output "$NEW/artifacts/malecns_weights_schema.json"
```

`inspect_feather.py`はデフォルトで全行をPythonリストにしない。ただし圧縮record batchを読み出す分のメモリは必要。行数全走査はM3のメモリ予算内で行う。

---

## M3. 集合・NT policy・疎結合を確定する

ここからは**Codexが新規実装する作業**。以下のファイルは、同梱済み／作成済みではない。

```text
Brain/MaleCNS/
├─ config/schema_map.json
├─ config/selection_policy.json
├─ config/nt_policy.json
├─ inspect_dataset.py
├─ build_sparse_graph.py
└─ results/dataset_audit.json
```

### M3-1. 採用集合を宣言する

初回は、annotationでニューロンとして識別できる集合を採用し、その集合内の接続を保持する方式を候補とする。brain/VNC両方を含むか、クラス別に確認する。細胞型が不明なニューロンも、type名が空という理由だけで落とさない。

保存する数値：

- annotation行数、重複ID数、採用N。
- raw接続行数、重複pre/post集計前後のE。
- 採用集合外を端点に持つedge数とsynapse count合計。
- 無結合ニューロンの扱い、自己結合の扱い。
- NT未同定・未対応ニューロン数、その出力edge数と重み合計。
- graph構造として保存したEと、非ゼロ重みとして実際に働くE。

**166,691や25,582,938に一致するようにフィルターを後付けしない。** 一致しない場合は定義・confidence cutoff・segment集合の違いを記録する。縮小graphは縮小graphと表示し、全CNS実行の証拠にしない。

### M3-2. NTからシナプス符号への変換

MaleCNSのNT予測は、それだけで受容体・電気生理・すべての符号と時定数を指定するものではない。Shiu型LIFを移す際は別のモデル仮定が入る。[S02][S04]

最初に既存Shiuモデルの符号付き重みの作り方・論文を確認し、`nt_policy.json`へ出典、カテゴリ、符号、信頼度閾値、未対応時の動作を記録する。

- 不明NTを黙って興奮性にしない。
- dopamine等を検証なしにAChと同じfast excitatory synapseへしない。
- `unknown=0`を使う探索モードを用意する場合、抑制したedge数を出し、完全な結合動態とは呼ばない。
- 厳格モードは未定義カテゴリで停止。PoC用の仮定は設定ファイルに明示してから採用する。
- synapse countを個別の物理シナプス全展開にする必要はない。集計した1 edgeへ重みを持たせる。

最初は既存と同じLIF方程式・dt・遅延・初期値・積分法を使い、**パラメータ移植自体が未検証であることを表示**する。既存Shiuソースのreset式などを読み直し、誤記が疑われても移植と同時に黙って修正しない。

### M3-3. メモリ予算

N×Nのdense配列、`.toarray()`、巨大なPython edgeタプルリストは禁止。元ID→連続indexの対応を作り、pre/post indexと符号付きweightの数値配列で保持する。

概算例として、E=2,560万なら`int32 pre + int32 post + float64 weight`だけで約410MB。これは**仮のEでの最低限の配列容量**であり、Brian2の管理構造、遅延キュー、Arrow、ソート、重複コピーは別に必要になる。ファイル1.1GBだからRSS1.1GBとは考えない。

初回RSS上限は、実機RAMの50%または8GiBの小さい方を作業用の暫定値とする。OSやUnityの余裕が不足する場合は下げる。構築中も別の軽量監視プロセスでRSSを監視し、上限超過時は結果を保存してそのPoC子プロセスを終了する。`step`終了時だけの確認では構築時ピークを防げない。

メモリ不足時は①一時表の解放とstream処理、②重複配列削減を先に行う。それでも不足なら小subgraphで動作確認し、全CNSは未達と報告する。OSのswapへ任せて無期限実行しない。

---

## M4. MaleCNS内でIDを同定し、上流→readoutを検証する

### M4-1. 旧IDを移植しない

旧FlyWireのDNa02/DNp09およびtop5 ID群は参考資料としてのみ保持する。MaleCNSではannotation、`type/instance`、提供されていれば`flywireType`等を使って候補を検索する。[S03]

候補名は`DNa02`、`DNp09`、必要時`DNa01`等。ただし同じ表記が必ず存在するとは仮定しない。左右の意味（soma側・投射側・type suffix等）も明示する。

`readout_mapping.json`へ保存：

```text
role / dataset / bodyIds（文字列） / reportedCellType / side
annotationSource / sourceVersion / evidence / verified / limitations
```

名前が確定しないものをDNa02と呼ばない。未解決なら匿名の`READOUT_A/B`として神経応答だけを確認し、「歩行／旋回ニューロン同定成功」とは報告しない。

### M4-2. 小さい数値テストを先に通す

公式データではない3〜数十ニューロンのtoy graphで以下を確認する。

- pre→post方向が逆転していない。
- 興奮性／抑制性の符号、遅延、単位が意図どおり。
- 無刺激baselineと刺激条件の区別。
- 1回runと分割runで状態保持が整合する。
- 観測countの差分をwindow秒で割る。

このtoy testはMaleCNS成功の証拠に含めない。

### M4-3. 結合から刺激候補を絞る

同定できたtargetへのpresynaptic候補を逆引きする。raw synapse countとNT policy適用後のsigned weightを両方表示し、抑制性候補を興奮性候補に混ぜて「top5」としない。

初回探索予算の例：targetあたり上位1群、最大3 target、無刺激を含め最大12条件。各条件1試行、まず100Hz・短い固定期間でscreeningし、有望条件だけ異なる3 seedで再検証する。対象DN自身の直接刺激は配線テストとして分離し、最終成功に数えない。

刺激対象と全readout IDの交差が空であることをassertする。無刺激比較だけでなく、有望経路の直接入力edgeを一時的に0にした対照も保存する。ネットワーク再帰入力が残るため、応答が完全0になることは必須にしない。

全体が飽和・発散した場合に、見かけのmotor値をclampして成功に見せない。まずデータ方向、符号、重み集計、入力強度を検査する。調整は別config・別結果として記録する。

### M4の合格

**MaleCNSの保存済み結合を使い、直接刺激していないreadoutの発火が入力条件で変わる。** 解剖学的名前を確認できた場合のみmotor-relatedと呼ぶ。3 seedはPoC再現性の確認であり、生物学的妥当性の検証ではない。

---

## M5. persistent controllerと校正

既存Shiuのpersistent実装を参考に新バックエンドを作り、原本を改変しない。[S04]

- Network構築1回。
- 内部dtと50msの読み出しwindowを区別。
- Action変更で状態resetなし。
- 刺激ON/OFF時のPoisson入力・不応期の扱いを明記。
- `SpikeMonitor(record=False)`等でcount差分を取得。
- 脳の計算workerは1つ。2つのネットワークへ同時に大量trialを投げない。

R/L/Fとして使えるreadoutが確認できた場合だけ、`STOP→F→STOP→R→STOP→L→STOP→F+R→STOP→F+L→STOP`を実行する。同時入力は実測し、個別結果の足し算にしない。

### 校正を分離する

Shiuの`forwardReferenceHz=120`、`turnReferenceHz=161`、`turnDeadzoneHz=45`はコピーしない。新データで校正用seedを使い、別seedをholdoutにする。readoutや尺度が未定義ならmotor出力をreadyにしない。

同じraw活動を再投入したとき、request Action名にかかわらず同じmotorが返るテストを入れる。入力名から出力を返すshortcutを防ぐ。

### 性能・解釈

cold構築／compile、warm 50ms step、raw読出し、RSSを別々に測定する。Unityなし／同時起動を分ける。平均・p50・p95・最大・サンプル数・実時間／脳内時間比を報告する。

**非同期化は画面を止めなくする手段であり、脳計算の遅さを消さない。** 50msの脳内時間に180msかかる旧実績なら、脳時間は実時間の約0.28倍で進んでいる。新MaleCNSが同じ速度になる保証はない。

本プロジェクトの暫定採用目標は、旧Mac実績を基準に「warm計算p95が250ms以下、Unityを含むE2E p95が500ms以下」を候補とする。これは医学的・生物学的基準ではなく**操作感のための提案値**。超えたら体感確認とプロファイルを先に行い、窓を縮めただけで計算がリアルタイム化したとはしない。

---

## M6. サーバーへ接続し、Windowsへ渡す

新サーバーは`127.0.0.1:8766`。Shiuの既存サーバーは8765のまま保護する。既存の`brain_server.py`にある実際のprotocolとthread所有規則を読み、別entrypointとして再利用する。

新規CLIの**実装契約例（まだ存在するコマンドではない）**：

```bash
python brain_server_malecns.py \
  --config config/malecns_v1.json \
  --backend cython --host 127.0.0.1 --port 8766
```

Codexが実装したあと、`--help`と実行結果をREADMEへ更新する。既存CLIの引数を想像で使わない。

必要な状態表示：

- `backendId = malecns_lif_poc`
- `datasetId = male-cns:v1.0`
- `dynamicsModel = shiu-style LIF adaptation`等、実装に一致した記述。
- 採用N/E、未知NTの扱い、cell-type mapping status。
- `ready=false`の間はゲーム入力を受け付けない／motorを有効化しない。
- record/replayは`REPLAY`、Shiuへのfallbackは`SHIU`と必ず表示。

旧HUDの`DNp09_Hz`へ別ニューロンの値を入れない。ゲーム用`motor.forward/turn`は維持できても、raw診断の名前・ID・校正は新しいものになる。詳細は`03_SHARED_CONTRACT.md`を参照。

### Windowsへ渡すもの

```text
Brain/MaleCNS/ のソース＋config
portable environmentの必要package一覧
データdownload manifestとSHA-256
selection_policy / nt_policy / readout_mapping
新校正JSON
実測BrainFrame fixture（6状態、欠測／errorを含む）
起動コマンド・既知制約・benchmark JSON
```

macOSのCython cacheやcondaフォルダーを渡さない。Windowsでnative依存を再構築する。

### LAN試験

まずlocalhostで完了させる。2台試験は信頼できる家庭内LANのみ。Macの実際のIPv4をネットワーク設定から確認し、そのアドレスへbindする。無認証サーバーをインターネットや会場の共有ネットワークへ公開しない。

Windows側は`Test-NetConnection <Macの実IPv4> -Port 8766`で到達確認し、その後Unityを接続する。E2Eは**送信と受信を同じWindowsの単調時計で測る**。MacとWindowsの時計値を直接引かない。

## Codexへ最初に貼る指示

```text
00_START_HERE.md、03_SHARED_CONTRACT.md、01_MAC_MALECNS_TEST.mdを読んでください。

担当はMac。既存Shiu環境とUnityプロジェクトは保護し、MaleCNSは別backendです。
既存パスは /Users/isaoohta/UnityGame/FlyBrain/Work 配下です。
新しい作業ルート候補は /Users/isaoohta/UnityGame/FlyBrain/Parallel です。

今回の実行範囲はM0〜M3まで。
1. 実ファイルと現在の依存・データ・校正pathを確認する。
2. 元環境を変更せずsnapshotとWindows引渡し契約を作る。
3. brian2環境をflybrain-malecnsへ複製する。
4. 公式配布のannotationとNT表を先に取得・schema検査する。
5. 接続表を取得し、採用集合、ID列、edge方向、NT policy候補を監査する。
6. メモリ予算を報告する。dense行列は禁止。

FlyWire root ID、旧top5、旧校正はMaleCNSへ流用しない。
この段階で全CNS LIFやUnityを起動しない。未定義のNTを勝手に興奮性にしない。
リポジトリ外の既存ファイルを変更しない。Git公開・pushは明示された宛先だけ。
新ファイル名やCLIはREADMEに実装済み／未実装を区別する。

終わったら、環境、取得した公式URL、SHA-256、schema、N/E、ID対応状況、
除外条件、NT未確定項目、メモリ見積り、Windowsへ渡せるものを報告してください。
```

M0〜M3完了後は「M4のみ」、その後「M5〜M6」と段階を分けて指示する。科学的対応が未確定なのに自動でmotorへ進めない。

## 出典

[S01] https://male-cns.janelia.org/  
[S02] https://male-cns.janelia.org/download/  
[S03] https://natverse.org/malecns/  
[S04] https://github.com/philshiu/Drosophila_brain_model/blob/main/model.py ／ https://www.nature.com/articles/s41586-024-07763-9  
[S05] https://brian2.readthedocs.io/en/2.5.1/introduction/install.html  
[S06] https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html （condaの環境複製・exportのリファレンス。作業時はインストール版の`conda --help`も確認）  
[S07] https://docs.unity3d.com/es/2020.1/Manual/ExternalVersionControlSystemSupport.html （Assets/Packages/ProjectSettingsと.metaの共有原則。Editor版は実プロジェクトで固定）
