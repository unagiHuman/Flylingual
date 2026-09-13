# Neural Visualization 統合手順

この機能は `UnityProject/Assets/BrainVisualization` と MaleCNS の既存 additive telemetry を組み合わせる独立 feature directory である。wire format の正本は [Neural Visualization v1 protocol](../../Contracts/neural-visualization-v1/protocol.md)。統合時も既存 Unity ファイル、Scene、package、共有設定、locomotion、CPG、Brain MotorDecoder、既存 TCP controller は変更しない。Windows 側の実 Brain と Unity の所有者が最後に統合する。

## 所有範囲

| 担当 | 内容 |
|---|---|
| Mac / feature | `neural_visualization.py` の atlas 検証、`export_visualization_atlas.py`、Contracts、統合手順 |
| Windows | portable annotation の用意、既存の controlled startup に任意 flag を追加、Unity prefab/Scene の opt-in、実 Brain Live 検証 |
| 既存 Bridge | `brain_server_bridge.py` が `brain_server_analog.parse_args()` を継承し、引数を子 server に渡す |
| 可視化 runtime | 既存 `BrainTcpClient.ReceivedLine` を読む subscriber。独自接続や送信はしない |

Atlas は次の相対 path に生成する。

`UnityProject/Assets/BrainVisualization/Resources/BrainVisualization/malecns-atlas.json`

生成 atlas は feature 内の private / regenerable asset として扱い、リポジトリでは `.gitignore` 対象にする。座標のある実 soma のみを使い、既定 24,000 点、最大 65,536 点。`missingRequiredCoordinateIds` と `omittedCoordinateCount` を確認し、これを全 neurite や全脳レンダリングの証拠に昇格しない。

## Windows portable exporter

Windows checkout のリポジトリ root で、Portable MaleCNS の Python を使う。`--annotations` は Windows 担当が配置した Feather の明示的 override であり、既定 Mac data path に依存しない。`metadata`、graph、config は同じ portable bundle の相対 path に置く。

```powershell
python Brain\MaleCNS\export_visualization_atlas.py `
  --metadata Brain\MaleCNS\config\analog_handoff_manifest.json `
  --graph artifacts\neuron_checkpoint `
  --config Brain\MaleCNS\config\analog_temporal_v1.json `
  --annotations Data\malecns\v1.0\body-annotations-male-cns-v1.0-minconf-0.5.feather `
  --max-neurons 24000 `
  --output UnityProject\Assets\BrainVisualization\Resources\BrainVisualization\malecns-atlas.json
```

相対 path は Flylingual root 基準で解決される。上記 metadata と graph は tracked/configured portable bundle の実在 path を使う。bundle の配置が異なる場合だけ Windows owner が同じ意味の相対 pathへ置換し、`--annotations` は必ず明示する。exporter は annotation の SHA-256 と manifest の値、graph ID の昇順性、finite somaLocation、required ID の座標欠落を検証する。出力 JSON の `atlasId`、`selectedNeuronCount`、`eligibleCoordinateCount`、`omittedCoordinateCount`、`missingRequiredCoordinateCount` を保存して統合レビューに渡す。上書き前に他の Unity/Brain process が asset を読んでいないことを確認し、稼働中 process を kill して競合を解消しない。

## Brain 起動

`--visualization-atlas` は `brain_server_analog.py` の既存 optional 引数であり、`brain_server_bridge.py` の inherited `parse_args` から同じ local path を渡す。flag の意味は atlas を検証して各 `brain_frame` に `visualization` window aggregate を追加することだけである。現在の実装は `windowMs=50`、`metric=window_spike_count`、atlas order の `bodyIds` と `spikeCounts` を出力する。

既存の Windows controlled startup に、既存の Brain command の末尾へ一度だけ次を追加する。

```text
--visualization-atlas UnityProject\Assets\BrainVisualization\Resources\BrainVisualization\malecns-atlas.json
```

launcher が自動でこの flag を付けることはない。Windows owner が既存 startup の同じ local atlas path に手動で append する。新しい二本目の Brain server、別 port、別 controller を起動しない。atlas 検証失敗は backend worker の初期化失敗となるため、server error として修正してから再起動する。起動後は `status` の backend/dataset/instance/session と、実際の frame の `visualization.atlasId` を atlas と照合する。対応 backend に telemetry が無い場合は無効状態を維持し、mock/replay/fixed motor を代用しない。

## Unity Editor の opt-in

既存 Sceneを直接変更せず、Editor menu を必要な検証担当だけが実行する。

1. `Tools/FlyBrain/Neural Visualization/1 Generate Prefab` で feature 内の Generated prefab/material を生成する。
2. atlas を Resources に配置した後、対象 Scene に既存 `BrainTcpClient` が **ちょうど1つ**あることを確認する。
3. `Tools/FlyBrain/Neural Visualization/2 Add To Current Scene` で opt-in 追加し、保存先と Scene 差分を目視確認する。
4. 静的 anatomy だけを確認する場合は `Tools/FlyBrain/Neural Visualization/3 Export Static Anatomy Preview` を使う。これは Editor preview camera の soma 座標を描くだけで、PlayMode、server接続、activity simulationを行わない。

生成 object は off-world `AnatomicalDisplay`、layer 31、専用 RenderTexture camera である。既存 gameplay camera の culling mask、UI input、physics、lighting、Scene共有 asset を変更しない。`NeuralActivityObserver` は単一既存 client の `ReceivedLine` を subscribe するだけで、control line を送らない。observer は既存 client 接続前に enable する。live 中の追加は Windows owner が controlled reconnect で行い、observer 自身は reconnect しない。`Configure` による安全な rebinding は許可され、session 切替時は panel の history を reset する。

追加 SerializeField の既定値は次のとおり。参照欄は C# 上では null、生成Prefabでは下記参照を設定する。

| Component | Field | Default |
|---|---|---:|
| `NeuralActivityObserver` | `source` | null（既存clientが単一なら自動購読） |
| `NeuralActivityObserver` | `atlasAsset` | null → 生成atlas参照 |
| `NeuralActivityObserver` | `pointCloud` | null → 生成点群参照 |
| `NeuralActivityObserver` | `staleSeconds` | `0.75` |
| `NeuralActivityObserver` | `bindSingleExistingClient` | `true` |
| `NeuralPointCloud` | `renderMaterial` | null → 生成material参照 |
| `NeuralPointCloud` | `pointSize` | `0.016` |
| `NeuralPointCloud` | `restingBrightness` | `0.5` |
| `NeuralPointCloud` | `spikeAfterglowSeconds` | `0.25` 秒 |
| `NeuralPointCloud` | `rateForFullGlowHz` | `45` Hz |
| `NeuralPointCloud` | `membraneScaleMv` | `2` mV |
| `NeuralPointCloud` | `displayGain` | `1` |
| `NeuralPointCloud` | `inheritLayer` | `true` |
| `NeuralPointCloud` | `spikeScale` | `1.5` |
| `NeuralPointCloud` | `spikeHaloScale` | `2.4` |
| `NeuralPointCloud` | `spikeGlowGain` | `2` |
| `NeuralPointCloud` | `showMembranePotential` | `false` |
| `NeuralVisualizationPanel` | `observer` / `pointCloud` / `brainCamera` / `displayRoot` | null → 各生成component参照 |
| `NeuralVisualizationPanel` | `visible` | `true` |
| `NeuralVisualizationPanel` | `screenWidthFraction` | `0.36` |
| `NeuralVisualizationPanel` | `textureResolution` | `768` |
| `NeuralVisualizationPanel` | `allowOrbit` | `true` |
| `NeuralVisualizationPanel` | `brainFocus` | `true` |
| `NeuralVisualizationPanel` | `brainFocusCenter` | `(0, 0.66, 0)` |
| `NeuralVisualizationPanel` | `brainViewSize` | `0.86` |
| `NeuralVisualizationPanel` | `fullViewSize` | `1.25` |

## Acceptance gate と未完了欄

受入れは Windows の実 Brain LiveTcp と Windows Unity の組合せだけで行う。最低限、atlas ID一致、metadata の dataset/instance/session/mode、sequence増加、window spike count、raw voltage subset、750 ms stale clear、duplicate age 非更新、disconnect clear、atlas mismatch clear、入力操作の非干渉を同一 run の JSONL と代表 frame で確認する。static anatomy の Mac Editor render/compile は別の静的 gate であり、Live acceptance の代替ではない。

操作レビューでは GUI mouse drag が orbit の GUI 入力だけを消費し、gameplay input を止めないことを確認する。加えて 24,000 点で payload、queue drop、JSON parse/main-thread、GPU/CPU/RSS の overhead を測定する。未対応 backend に spike を補う実装は受入れ対象外。

### 2026-09-12 Macで確認した結果とWindowsの残作業

- Windows 実 Brain Live: **PENDING** — backend、instance/session、実測 frame 数、sequence 範囲、stale/error 数を記録する。
- atlas counts: **CONFIRMED** — `atlasId=0ceadfb2e5c3b07e57302cc3cd1f2e16661f1d2f3596199da5ddabc23eb7ec01`、graph `166700`、eligible `139662`、selected `24000`、omitted `27038`、missing required `0`。実データ生成とgraph ID対応を確認。50ms窓内最大500発/細胞を仮定したcompact visualization JSONは300,310 bytesであり、ネットワーク実測値ではない。
- Unity static anatomy Editor render/compile: **PASSED** — Unity 6000.5.5f1、2026-09-12 14:45 UTCの最終確認。C#・shader error 0、可視化コードのC# warning 0。最終ログには既存ファイル由来のC# warningが18種類残る。独立Prefab/material生成と、24,000 somaの静止画を確認。Mac静的確認をWindows Liveの証拠としない。
- Windows Unity Live操作・stale・mismatch・overhead: **PENDING** — mock/replay の結果で置換しない。

証拠はGit外の `artifacts/neural-visualization/validation.json`、`atlas-export.json`、`final-compile-preview.log`、`static-anatomy.png`。画像は活動値を与えていない静止した解剖座標であり、発火確認画像ではない。PlayMode、Brain接続、新規神経simulation、Windowsビルドは実施していない。

初期dirty 12ファイルはSHA-256で一致を確認して保持した。Unityが自動変更した共有URP設定は開始時の内容へ復元済み。既存Scene、Unity受信コード、Packages、ProjectSettingsへの本機能の差分はない。新規Unityコードとmetaは `Assets/BrainVisualization` 配下およびフォルダーmetaだけ。既存Pythonの変更は `analog_controller.py`、`brain_server_analog.py`、`brain_server_bridge.py` の3ファイル。新規Python2ファイルと、本書・protocolの定義ファイルも追加した。commit/pushは未実施。

診断表示はstate、mode、ready、frame age、sequence、sample/active/spikes、SKIP。追加ログキーは `NEURAL_VIS_ATLAS_INVALID`、`NEURAL_VIS_PREFAB_READY`、`NEURAL_VIS_STATIC_PREVIEW`。パネルの統計は表示サンプルと受信窓についての値であり、全CNSの総発火数や観測していない時間の合計とは呼ばない。


## 白灰・赤橙デザイン（2026-09-13）

既存の24,000 somaサンプルを保持し、未観測の構造は灰色、スパイク窓を観測済みでゼロの点は白、実測発火は赤橙で表す。発火後0.25秒の表示残光と最大1.5倍の中心径を使う。奥の点をわずかに暗くする。構造はpremultiplied alpha合成とし、発火部分のグローは後述の強調設定を使う。電圧のみの点は「発火なし」と判定しない。膜電位色は既定OFFで、必要時に `ShowMembranePotential` またはInspectorから有効にする。

既定の画角は脳の拡大表示。独立パネルの `FULL CNS` / `BRAIN FOCUS` ボタンで切り替える。`SetBrainFocus(bool)` は埋め込み先からも呼べる。既存Play Screenの `SetEmbedded` / `Rotate` / `Zoom` / `DisplayTexture` APIは維持し、そのファイルは変更しない。埋め込み中は独立パネルのボタンを表示しないため、専用切替ボタンを必要とする場合はWindows側UI担当がこのAPIへ接続する。既存のホイールによる拡大縮小は引き続き使える。

`brainFocusCenter` は現在の正規化atlasに合わせた表示上の中心であり、脳細胞の分類やデータの選別ではない。点群自体は削除せず、回転時もこの中心をカメラが追う。全シナプスや全神経突起の表示を追加したものではない。

既に生成済みのPrefabには古いSerializeField値が残るため、独立機能の `1 Generate Prefab` で再生成する。独自のScene overrideは勝手に書き換えず、必要な値をInspectorで上表に合わせる。Play Screenが実行時に新しく作成する点群には新しい既定値が適用される。`3 Export Static Anatomy Preview` は全体の `static-anatomy.png` と拡大の `static-brain-focus.png` を出力する。どちらも活動入力なしの静止画。

今回の変更対象は可視化の描画2ファイル、パネル、専用Builder、および本定義ファイルだけ。Brain計算・受信データ・既存Play Screen・共有Scene・ProjectSettingsは変更しない。検証結果は `artifacts/neural-visualization/design-white-red/` に保存する。Windows実Brainでの発火・残光・回転・画角切替・操作非干渉は引き続き未検証。

2026-09-13 03:25 UTC確認：対象projectは6000.5.9f1、Macのインストール済みEditorは6000.5.5f1のため、一時コピーで同じC#・shaderソースとPackagesを使ってコンパイル・静止描画した。エラー0、可視化コードの警告0、他のC#警告47種類。全体・拡大のPNGを目視確認済み。6000.5.9f1自体の検証、PlayMode、発火・残光の実測とは区別する。ソース側のProjectVersion/ProjectSettingsは変更していない。

今回の再生成Prefab/materialは既存の生成asset GUIDを保持してローカルのGeneratedへ反映済み。開始時に変更中だった9ファイルは内容のSHA-256一致を確認。追加された他タスクのファイルもそのまま保持した。commit/pushは未実施。新規ログキーはなく、静止画出力には既存の `NEURAL_VIS_STATIC_PREVIEW` を使用する。


## 発火グロー強調（2026-09-13）

発火した点は暖白色の中心と赤橙色の広い光で強調する。既存の非ゼロ `window_spike_count` を受け取った時刻から短いフラッシュと残光を描き、低い発火率も見分けやすくする。これは受信窓を読みやすくする表示効果であり、個々のスパイクの正確な時刻を再現するものではない。周期的・ランダムな点滅は追加せず、電圧だけの観測では発光させない。新たなゼロ窓では直前の残光が減衰し、stale/disconnectの既存 `ClearActivity` では即座に消える。

光は専用点群shader内で合成するため、既存のLDR RenderTextureでも使用できる。共有Bloom、Volume、カメラ設定、Play Screen、受信処理、Sceneは変更しない。灰白色の構造表示と表示ゲイン操作を維持する。多数の点が同時発火するとLDR出力の明部が飽和しうるため、最終的な強さと密集部の見え方はWindows実Brainで確認する。

追加調整項目は `spikeHaloScale=2.4`（光の最大径倍率）と `spikeGlowGain=2`（実測活動から表示強度への変換ゲイン）。既存 `spikeScale=1.5` は中心径、`spikeAfterglowSeconds=0.25` は残光時間を維持する。フラッシュは残光時間の32%（既定80ms）、実測窓の到着ごとに更新する。

2026-09-13 05:53 UTC検証：対象と同じUnity 6000.5.9f1で、Assets/Packages/ProjectSettingsを複製した一時projectをコンパイルし、活動入力なしの静的anatomyを描画。C#・shaderコンパイルエラー0、可視化C#警告0、他のC#警告48種類。描画ソースの一致と脳拡大PNGを確認した。ログ・静止画・validation.jsonは `artifacts/neural-visualization/glow/`。生成Prefab/materialを既存GUIDを保持してローカルGeneratedへ反映。Windows実Brain、PlayMode、実際のグロー・点滅・描画負荷は未検証。変更は描画2ファイルと本定義ファイルのみで、並行作業中のBridge変更は保持。新規ログキーなし、commit/pushなし。
