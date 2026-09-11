# Windows手順書：既存デモ再現・リアルVisual・MaleCNS受入れ

版1.0／2026-09-11 JST

## 0. 担当の目的

**Macが新しいMaleCNSを検証している間、Windowsは現在動作するShiu版でゲーム側を完成へ進める。** MaleCNSの神経探索はWindowsで重複しない。

Windowsでの優先順：

1. ソースを受け取り、既存Shiu Brain＋UnityをWindows単体で再現。
2. 物理を変えず、Blender MCP等でリアルなハエVisualを制作。
3. Backend名・実測神経活動・Grip・通信状態を表示し、デモをビルド。
4. MacのMaleCNSが合格したら、同じゲーム用motor入力へ接続。
5. 最終的に採用した脳とUnityをWindowsノート1台で動かす。

Macでの実測値をWindowsの性能保証として使わない。RTX搭載であっても、今回のBrian2/Cythonを自動でCUDA化しない。CPU実装で再現を優先する。[S05]

---

## W0. 作業開始前の確認

作業先は新規提案として`C:\Dev\FlyBrain\Parallel`。Windows既存パスがある場合は調整する。

PowerShell：

```powershell
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-CimInstance Win32_VideoController | Select-Object Name
Get-Command git -ErrorAction SilentlyContinue
Get-Command conda -ErrorAction SilentlyContinue
Get-Command codex -ErrorAction SilentlyContinue
```

Macで確認済みのEditorは6000.5.5f1だが、**受け取った`ProjectSettings/ProjectVersion.txt`を正**としてUnity Hubから同じ版とWindowsビルド用モジュールを導入する。別Unity版への自動upgradeは禁止。

Brain実行は最初からWindows native Pythonを使う。今回はWSL、Docker、CUDA、GPUクラウドを混ぜない。これは技術制限ではなく、移植時の切り分けを減らすための選択。

## W1. ソース受領

### W1-1. Macから受け取るもの

`03_SHARED_CONTRACT.md`の引渡し仕様に従う。

- `Brain/ShiuBaseline`：原本ではなく成功ソースsnapshot。
- Shiuのデータと校正JSON。大容量データはGitと別経路でもよい。
- `UnityProject/Assets`、`Packages`、`ProjectSettings`と`.meta`。
- `Contracts`：実際のNDJSON、Action一覧、fixture、backend metadata案。
- `Docs/baseline_manifest.json`、package一覧、起動コマンド。

`.app`をWindowsで使おうとしない。Windows用Playerをソースから作る。Macの`Library`、Cython cache、conda環境を流用しない。[S07]

### W1-2. private Gitの利用例

ユーザーが選んだ共有リポジトリが存在する場合のみ：

```powershell
New-Item -ItemType Directory -Force 'C:\Dev\FlyBrain' | Out-Null
$RepoUrl = Read-Host '共有用private GitHubリポジトリのURL（トークンを含めない）'
git clone $RepoUrl 'C:\Dev\FlyBrain\Parallel'
Set-Location 'C:\Dev\FlyBrain\Parallel'
git switch -c feat/windows-demo
Get-Content '.\UnityProject\ProjectSettings\ProjectVersion.txt'
```

すでにclone済みなら`git status`を確認し、`git pull --ff-only`で更新する。変更中のものを`reset --hard`で捨てない。

Git未準備の場合は、Macのsource snapshotアーカイブを新規ディレクトリへ展開する。復元後にhash/ファイル数を比較し、以後の共同編集はGitで管理する。

### W1-3. portable依存ファイルを作る

Macの`pip freeze`をそのまま`pip install -r`へ渡さない。condaが入れたパッケージをpipで置き換える可能性がある。Mac固有パッケージやbuild識別子も除く。[S06]

Codexに次を読ませ、`Brain/ShiuBaseline/environment-windows.yml`を作らせる。

- 原本の`environment.yml`。
- Mac成功環境のpackage inventory。
- 実行に使う`brain_server.py`とそのimport。

原則としてPython 3.10、Brian2 2.5.1、Cython 0.29.37を維持。NumPy、pandas、pyarrow、joblib、setuptools等はMac成功版を先に試す。Windowsで配布のない版のみ、変更理由と差分を記録する。Cython 3.xへ勝手に戻さない。

---

## W2. Windows側のShiu Brainを再現する

### W2-1. C++ compiler

Brian2のWindows runtime Cython backendにはVisual Studio C++ compilerが必要。Build Toolsで対応するMSVC toolsetとWindows SDKを入れる。フルVisual Studioは必須ではない。[S05]

Developer PowerShell等で`cl`が利用できるか確認する。

```powershell
where.exe cl
conda --version
```

`cl`が通常PowerShellのPATHにないだけでは失敗確定ではないが、最小Cython試験を通すまでは全脳を起動しない。Mac用の`CC=/usr/bin/clang`、`CXX=/usr/bin/clang++`はWindowsへコピーしない。

### W2-2. 環境作成

以下のYAMLはW1でCodexが作成・確認したものを使う。

```powershell
Set-Location 'C:\Dev\FlyBrain\Parallel'
conda env create -n flybrain-shiu-win -f '.\Brain\ShiuBaseline\environment-windows.yml'
conda activate flybrain-shiu-win
python -c "import brian2, Cython, numpy, pyarrow; print(brian2.__version__, Cython.__version__, numpy.__version__, pyarrow.__version__)"
```

`environment_probe.py`を展開したGuideフォルダーから実行し、結果を`artifacts/env/windows_shiu.json`へ保存する。

### W2-3. Cython最小試験

```powershell
@'
from brian2 import NeuronGroup, Network, ms, prefs
prefs.codegen.target = 'cython'
g = NeuronGroup(1, 'dv/dt = -v/(10*ms) : 1', method='euler')
Network(g).run(1*ms)
print('Cython minimal test: PASS')
'@ | python -
```

失敗時は完全なstderrを保存。NumPy fallbackを成功扱いにしない。

### W2-4. データ・校正・cache path

`poc_config.py`を確認し、Macの絶対パスが残っていないか検査する。

- Shiu v783のcompleteness／connectivityは同じ内容・hash。
- MotorDecoderが読む校正JSONも同じもの。
- cacheはWindows専用ディレクトリへ。Mac生成物は使わない。
- 出力先は`artifacts/windows-shiu`等、Mac結果を上書きしない場所。

必要なpath修正は新snapshot側だけ。方程式、dt、神経ID、重み、校正は変更しない。

### W2-5. 既存サーバーを起動

実装の`--help`とREADMEを先に読む。会話で成功している起動形式が同じなら：

```powershell
Set-Location 'C:\Dev\FlyBrain\Parallel\Brain\ShiuBaseline'
python brain_server.py --backend cython --host 127.0.0.1 --port 8765
```

READYまで待つ。初回コンパイル時間をwarm性能へ混ぜない。

別PowerShellから既存Mock Clientを使う。**CLI引数は現物に合わせ、ここで想像しない。** 6 Actionを各1回、STOP／再接続／unknown actionを確認すれば初回移植試験は十分。

異OSでスパイク列が完全一致することは無条件の必須条件にしない。データ、モデル設定、Actionに対する符号、無刺激時の動作を比較し、大きな差があれば先に原因を調べる。

## W3. Unity単体起動とBrain接続

`UnityProject`を同じEditor版で開く。元の`BrainIntegrationPoC.unity`、次に`FlyLocomotionSandbox.unity`を順に試す。

```text
Windows Unity → localhost:8765 → Shiu Brain → BrainFrame.motor → PhysicsRig
```

確認項目：

- Rigidbody Capsuleで接続・6 Action・stale入力ゼロ化。
- 物理6脚で前進と左右旋回の符号。
- rootへの直接駆動を追加していない。
- Visual追加前の速度、yaw、姿勢、frame age、p95 frame timeを保存。
- Windows E2Eを計測。旧Macの約358msに一致することではなく、実測値を保存する。

MacとPhysXの軌跡が違っても、この工程で大量の歩容再調整を始めない。まず設定、初期姿勢、Fixed Timestep、gravity、unit、build条件、fixture入力を揃える。

この時点のWindows Playerを基準ビルドとして保存する。

### WindowsのCython互換で止まった場合

Visual担当まで停止しない。既存の`ReplayMotorSource`と受領した実測BrainFrame記録、または既存Mock入力を使ってW4の見た目を先行できる。その画面と記録には必ずREPLAY／MOCKを表示する。これはW2/W3の実Brain統合合格の代わりではなく、独立作業を進めるための経路。Cython互換は別タスクで解決し、最終W6では実Brainを再確認する。

---

## W4. リアルなハエVisualを制作する

### 物理と表示の分離

```text
PhysicsRig（既存。変更しない）
  Thorax＋6脚×主要3関節＋FootPad
               ↓ 実際の関節姿勢
VisualRigMapper
               ↓
VisualRig（新規。Collider・ArticulationBodyなし）
  頭、複眼、触角、胸部、腹部、翅、脚、足先、毛
```

主要18関節を対応させるが、単純な同名rotationコピーで必ず合うとは考えない。rest pose、joint axis、mesh pivot、脚長、左右反転、座標系を校正する。

足先が実際のFootPadから離れて浮く／床へ深くめり込む見た目にならないようにする。必要なら**Visual側の骨・メッシュ配置を調整**し、最初から物理リグをリアルモデルの寸法へ作り直さない。

### W4-1. asset候補の取扱い

第一候補はFlyGym/FlyBody等の科学的形状をベースにし、Blenderで見た目を整える方式。ただし、この手順パックにはmesh自体は含まれていない。

取得するファイルごとに、出典、version/commit、コードとは別のassetライセンス、再配布条件、変更点を`VisualSource/ASSET_PROVENANCE.md`へ記録する。**リポジトリ本体のApache/MIT表示だけで全外部meshの条件を決めない。** 未確認assetは配布ビルドへ入れない。

MaleCNSは雄のCNSデータ。採用したVisualが雌モデルだった場合、見た目を雄相当に加工したのか、単に別個体の表示モデルを使ったのかを区別する。外見を変えただけで同一個体のデジタル複製とは呼ばない。

### W4-2. Blender MCP

Blender MCPは第三者製ツールで、Blender内のPython実行等が可能。作業専用`.blend`をバックアップし、Blender/Codexは通常ユーザー権限で使う。外部生成APIの課金・データ送信は今回許可しない。ローカル接続だけで始める。[S09]

`uv/uvx`、Blender、Codexがすでに使えるか確認：

```powershell
Get-Command uvx -ErrorAction SilentlyContinue
codex --version
codex mcp --help
```

uvがない場合は公式のインストール手順で導入する。Blender MCPの現在のREADMEで確認できた初期登録例：[S08][S09]

```powershell
codex mcp add blender -- uvx --python 3.11 blender-mcp
uvx --python 3.11 blender-mcp install-addon
```

BlenderでAdd-onを有効にし、3D ViewのNサイドバーにあるMCPパネルから開始する。既存addonの導入済み環境は重複インストールしない。まずscene情報取得とcubeを1つ作って削除する疎通だけ確認する。

初回の動作確認後、解決されたblender-mcp版・Blender版を記録し、MCP server/addonを対応する版に固定する。既存`brian2`のPythonをMCPのためにupgradeしない。Blender MCPは1つの接続先だけで操作し、複数Codexが同じsceneを同時編集しない。

### W4-3. 最初のVisual成果物

`VisualSource/FlyVisual.blend`を正本とし、Unity用にはFBX＋画像texturesを明示的にexportする。`.blend`の直接importを本番ビルドの必須依存にしない。

最初の見た目の優先順：

1. 6脚と頭・胸・腹・翅の正しいシルエット。
2. 主要18関節の追従、足先の接地位置。
3. 複眼、翅の透過と翅脈、腹部模様、控えめな体毛。
4. カメラと照明。

Blenderのノード材質やGeometry NodesがFBX経由で同じ見た目になると仮定しない。必要なbase color／normal／roughness等は画像へbakeし、Unityの実際のrender pipelineに合わせた材質を作る。既存URP/HDRP/Built-inを勝手に変更しない。[S10]

初回は手動skin weightまたは分割meshの剛体追従を選び、auto weightの結果をそのまま信頼しない。翅の振動は見た目だけとし、揚力やroot forceを発生させない。

### W4-4. Visual専用Scene

新規`Assets/VisualDemo/`と新規Sceneで検証する。旧Sandbox Sceneは保存する。

- 正面・側面・上面・斜めの画像を保存。
- Brain FORWARDで歩く映像を保存。
- renderer OFFでもphysicsが同じように動くか比較。
- Visual由来のCollider/Rigidbody/ArticulationBody追加が0。
- 18主要関節とFootPadの数、mass、drive、物理設定が不変。

見た目が合わない場合は「physicsが正しいから完成」としない。接地の見え方を目視で評価する。

---

## W5. デモとHUD

デモSceneは最初、成功実績のある平地と低い段差だけにする。5cmを通すために複雑な反射を追加する研究へ戻らない。

HUDでは以下を区別：

- 現在のbackend：SHIU / MALECNS LIF PoC / REPLAY / MOCK。
- requested Actionと実際に適用されたrequestId。
- raw神経活動とdecoded motor。
- 実時間でのframe ageとE2E。
- Grip状態は実測できたものだけ。未知の必要力を正確な荷重として表示しない。

落下ゲーム性を試す場合も、有限粘着で実際に剥離し重力で落ちることを確認する。離脱したらTransformを落下位置へ飛ばす方式は採用しない。通信障害によるstale解除はゲーム中の自然な剥離と別に表示する。

6 Actionと落下／リスタートを含む短いデモ導線を作る。録画再生はバックアップとして用意できるが、LIVEと偽って見せない。

---

## W6. MaleCNSの受入れ

MacのM6合格までは実施しない。それまでShiu版または明示されたfixtureで開発する。

### W6-1. 2台接続

Mac担当が新サーバーの実IPv4・port・READYを通知した後：

```powershell
$MacIp = Read-Host 'MacのローカルIPv4'
Test-NetConnection $MacIp -Port 8766
```

Unityのhost/portを設定する。`127.0.0.1`はWindows自身でありMacではない。

- 新backend名が正しく表示される。
- 6 Actionの神経応答とmotorを確認。
- Unityの移動は`BrainFrame.motor`のみ。
- Missing readoutはN/A。旧DNa02欄へ無関係な値を流さない。
- stale timeoutはwall-clockのframe ageで判定。
- 遅いときにthresholdだけを無限に伸ばして失敗を隠さない。

### W6-2. Windowsへの新脳移植

Macが渡したコード・data manifest・NT policy・校正を新環境`flybrain-malecns-win`へ導入する。Shiu用環境とは分ける。CythonをWindowsで再コンパイルし、少数の数値テスト→persistent→TCPの順に検証する。

モデルIDや校正をWindowsで独自に変更しない。不具合修正はMac担当へ小さい差分として戻す。MaleCNSがWindowsで未達なら、本番はShiu版と正しく表示して動かす。

### W6-3. 最終パッケージ

```text
Demo/
├─ FlyGame.exe ＋ Unity Player必要ファイル
├─ StartDemo.ps1
├─ StopDemo.ps1
├─ brain/             # 対応するPythonソース・設定
├─ data/              # 必要データ、配布条件に従う
├─ licenses/
└─ README_DEMO.md
```

`StartDemo.ps1`は採用backendを明示し、port使用確認→Brain起動→READY待ち→Unity起動の順にする。生成したPIDだけを終了し、無関係なPython/Unityプロセスを一括killしない。cold compileとwarmを区別する。

本番の単体動作は、LANを切ったWindowsで実際に試す。ローカル脳データ・Python環境が揃っていることを確認し、APIを使う追加LLM機能がある場合は別の接続要件として明記する。

---

## Windows版の合格チェック

| Gate | 合格条件 |
|---|---|
| W1 | ソース・.meta・データhash・校正の受領が完了 |
| W2 | Shiuがnative Windows Cythonで起動し6 Actionを返す |
| W3 | Unity 6脚が実Brain出力で移動、stale・再接続正常 |
| W4 | リアルVisualが追従。物理を変更していない |
| W5 | backend表示・操作・落下／リスタート・映像が確認可能 |
| W6 | 採用backendをWindows1台で起動。未採用backendを偽装しない |

同じ初期条件の反復3回は再現性確認であって、独立な統計的成功率の証明ではない。大きな新機能より、固定した条件で再起動・復元できるデモを優先する。

## Codexへ最初に貼る指示

```text
00_START_HERE.md、03_SHARED_CONTRACT.md、02_WINDOWS_DEMO_VISUAL.mdを読んでください。
担当はWindowsです。MacはMaleCNS探索を行うため、それを待たず既存Shiu版で作業します。

作業先候補は C:\Dev\FlyBrain\Parallel。
初回の範囲はW0〜W3だけです。

1. ソースと.meta、データ、校正、実NDJSON契約を確認する。
2. ProjectVersion.txtと同じUnityを利用する。
3. Mac package一覧から必要なWindows依存を整理し、独立したnative Windows環境を作る。
4. Brian2/Cython最小compileを通す。Macのclang指定・cacheを流用しない。
5. 既存Shiu Brainをlocalhost:8765で起動する。
6. 既存Unity Capsuleと6脚を接続し、6 Action／stale／再接続を実測する。

旧公式model.py、神経ID、校正、CPG、joint、FootPad、摩擦を変えない。
必要なWindowsパス・起動互換の修正だけをsnapshot側へ行う。
データセット探索、MuJoCo、GPU化、Blender制作はこの初回ではまだ行わない。
完了後、実行方法、p95 step/E2E、Console、変更ファイル、基準ビルドを報告する。
```

W3合格後に「W4のVisualのみ」、その後「W5」、Mac合格後に「W6」と進める。

## Blender/Codexへ渡すVisual制作指示

```text
WindowsのW3が成功したため、W4のVisual専用制作へ進んでください。
現在のPhysicsRig、18主要関節、FootPad、mass、drive、CPG、Brain通信は変更しません。

Blender MCPを通常ユーザー権限・ローカル接続で使い、作業用blendを保存してください。
科学的なDrosophila形状を候補にしますが、使うmeshの出典・ライセンス・取得版を先に記録。
外部生成サービスへのupload、課金、モデル購入は行わないでください。

最初はシルエット、18関節対応、足先接地を優先。
複眼、半透明の翅と翅脈、腹部、触角、控えめな毛を表示用に整える。
blendはVisualSourceへ、FBXとtexturesはUnityのAssets/VisualDemoへ出す。
Blender材質をそのままUnity材質と見なさず、必要ならbakeしてUnity側で再構成する。

VisualRigMapperはrest poseと軸差を校正する。単純rotationコピーで済むと仮定しない。
Visual側に物理componentを追加しない。視覚用の翅は揚力を作らない。
新しいSceneで正面・側面・上面・斜めの画像と実Brain歩行映像を確認する。
既存Sandboxは上書きしない。目視未実施なら未実施と明記する。
```

## 出典

[S05] Brian2 Windows Cython要件：https://brian2.readthedocs.io/en/2.5.1/introduction/install.html  
[S06] conda環境：https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html  
[S07] Unity外部VCS：https://docs.unity3d.com/es/2020.1/Manual/ExternalVersionControlSystemSupport.html  
[S08] OpenAI Codex MCP：https://developers.openai.com/codex/mcp/  
[S09] Blender MCP第三者実装：https://github.com/ahujasid/blender-mcp/blob/main/README.md  
[S10] Blender FBX：https://docs.blender.org/manual/en/4.1/addons/import_export/node_shaders_info.html
