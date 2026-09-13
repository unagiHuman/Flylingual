# Blind Sugar Run 独立プロトステージ

基準：[Astra向け実装指示書](Blind-Sugar-Run-Implementation-Instructions.md)。今回の担当は、別セッションのハエ指示・移動修正と競合しない独立環境の作成と正式起動Sceneへの統合。

2026-09-13追記：`BlindSugarRunPlay.unity` を正式なWindows起動Sceneとして生成済み。既存 `FlylingualPlay.unity` のFly身体、Brain、会話、音声、Play UIを複製し、旧環境rootだけを新Environment Prefabへ置換した。既存Flyは `(0, 1.45, 0)` のまま、支持面上面は `y=0`。body配下の全Component serialization不変をBuilder内で検査している。旧 `AscentGameSession` のGoal判定は無効化し、新Goal判定とFinal Revealは未接続である。

## 構成と担当境界

新規配置先は `UnityProject/Assets/BlindSugarRunPrototype/`。環境だけの `BlindSugarRunPrototype.unity` と、後で別シーンへ配置できる `BlindSugarRunEnvironment.prefab` を維持する。統合済み起動Sceneは `BlindSugarRunPlay.unity`。既存の会話用シーン、Brain、Bridge、CPG、MotorDecoder、Flyの設定は変更しない。正式起動Sceneの追加とBuild対象先頭化だけを行う。

現段階のSceneはDeveloper View用。ハエ・会話・移動処理・Blind UIを含めず、ネットワークサービスを起動するComponentも置かない。Goal/Killは未接続のTrigger形状、SpawnとRevealはTransformの配置目印として用意する。ゲームのゴール判定・落下復帰・Final Reveal再生の実装完了とは扱わない。

## レイアウト

```text
                  砂糖の皿
               ／          ＼
          狭い近道        広い迂回路
               ＼          ／
                  本の広場
                     ／
                斜めの定規橋
                  ／
               向き合わせ広場
                     ↑
                安全な開始地点

           定規橋の下：落下受け皿
```

左右は開始地点から+Z方向を向いた場合。全ルートの歩行面を高さ0にそろえ、最初は段差と傾斜を難所にしない。定規への進入角は約20.6度。入口の広場で向きを整え、橋上の旋回を減らす課題とする。

寸法は既存リグの縮尺に合わせた仮値。`FlyLocomotionConfig.asset`のThorax寸法は1.4×0.7×1.8 Unity unit、脚の張り出しを含む横幅は読み取り上およそ4.2〜4.5 unitと見積もられる。歩行時の足先軌道・停止余動は未実測なので、身体の縮尺を変えず地形側を調整する。

| 区画 | 幅・長さの初期値 | 狙い |
|---|---|---|
| Start | 28×24 | 前進・停止・左右旋回を試す広場 |
| Alignment | 22×20 | 定規へ入る前の向き合わせ |
| Ruler | 幅8・長さ約25.6 | 両側の縁を意識して歩く |
| Book | 24×24 | 橋の後に止まり、分岐を相談する |
| Narrow | 幅6・中心線長23 | 短いが横ずれの余裕が少ない |
| Wide | 幅12・中心線長約56 | 長いが広い。曲がり角に14×14の足場 |
| Sugar | 26×20 | 最後に落ち着いて停止できる広場 |
| Catch | 36×36・上面高さ−6 | 橋下の受け皿。復帰処理は後で接続 |

所要時間10〜15分と各足場の適切な難度は、ハエ操作の修正後にWindows実Brainで通行・反復を測って調整する。静的なルート連続性だけでは通行成功としない。

## 他セッションが統合する接点

- `Anchors/Start`：仮のThorax中心位置 `(0, 1.45, 0)`、向き+Z。採用リグの初期化方法を確認して配置する。
- `RulerEntry` / `RulerExit` / `Branch` / `NarrowRoute` / `WideRoute` / `Goal`：区間の位置目印。
- `CatchRecovery`：受け皿上の仮配置目印。復帰方式は今回確定しない。
- `Volumes/GoalVolume`：砂糖付近の判定領域。将来、既存Flyの身体と安定時間を照合する。
- `Volumes/KillVolume`：コース下の境界領域。ゲーム失敗と接続障害を区別する処理が必要。
- `RevealCameraAnchors`：最後のカメラ演出用の位置目印。GPTへの観測入力には渡さない。

環境Prefabは原点・回転0・scale1で配置する。支持面はBoxCollider、飾りはColliderなし。ローカル観測実装時は、近傍の支持面とランドマークだけを対象にする。環境全体のTransform一覧や経路点をGPTへ渡さない。

既存のFlyは独立した物理Prefabではなくシーン内に構築されている。別セッションの修正後に採用リグを選び、既存の接続・初期化経路で統合する。旧デモのBuilderを実行して複製すると設定・制御処理まで変わるため、そのまま使わない。

環境へ `FlyGroundMarker` を追加する必要性も採用するリグ側で確認する。今回は共有スクリプト依存を作らず、純粋な環境アセットとして引き渡す。

## 生成・検証方法

生成元は [BlindSugarRunStageBuilder.cs](../../tools/authoring/BlindSugarRunStageBuilder.cs)。既存シーンを開いて改変せず、Unity APIで新規SceneとPrefabを生成する。

[New-BlindSugarRunStage.ps1](../../tools/authoring/New-BlindSugarRunStage.ps1) は `artifacts/blind-sugar-run-stage/` 内に独立した一時Unityプロジェクトを作る。共有プロジェクトの描画設定を読み取りコピーし、生成・再読込・静的検証・PNG撮影を行う。共有Editorの検証枠が解放された後に実行する。

```powershell
# リポジトリルートで実行。既存の生成先がある場合は上書きしない。
.\tools\authoring\New-BlindSugarRunStage.ps1 -Publish
```

`-Publish` を省略すれば一時プロジェクト内だけに出力する。共有Assetsへコピーする対象は新規 `BlindSugarRunPrototype` フォルダーとそのmetaだけで、生成用C#はコピーしない。Play Mode、Brain、GPTは使用しない。

確認対象は、両ルートの支持面の連続性、橋の側方の空き、寸法、TriggerとAnchor、Scene/Prefabの再読込、共有スクリプト・物理身体が含まれないこと。PNGで形状と外観も確認する。これらは幾何・アセットの検証であり、Phase 1の既存Flyによる通過やPhase 2の実Brain完走は別の検証として残す。

## 実行結果

2026-09-13、別セッションから共有実行資源の解放連絡を受けた後に実行。Unity 6000.5.9f1の独立した作成用プロジェクトでScene／Prefabを生成した。

- [環境Scene](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunPrototype.unity)
- [環境Prefab](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunEnvironment.prefab)
- [全景PNG](../../artifacts/blind-sugar-run-stage/authoring-20260913-125037-428/overview.png)／[上面PNG](../../artifacts/blind-sugar-run-stage/authoring-20260913-125037-428/topdown.png)
- [静的検証結果](../../artifacts/blind-sugar-run-stage/authoring-20260913-125037-428/validation.json)
- [取り込み・保護ファイル照合結果](../../artifacts/blind-sugar-run-stage/authoring-20260913-125037-428/publish-validation.json)

最終検証は `PASS_STATIC_GEOMETRY`。両ルートの中心と左右2.2 unitの位置で計1,185点の下向きRaycastを行い、上面高さ0の支持面を確認した。橋の中央部の両側が空いていること、幅8／6／12、GoalとKillのTrigger、8つの配置Anchor、環境Rootの原点・回転・scale、飾りにColliderがないこと、Scene／Prefabの再読込を確認した。MonoBehaviour、Missing Script、Rigidbody、ArticulationBodyは含まれない。

全景と上面画像を目視し、開始地点、斜めの定規、本、両分岐、砂糖の皿が確認できた。共有AssetsにはScene・Prefab・7つのMaterialと各metaをコピーした。共有の操作・Brain・会話・既存シーン・ProjectSettings等、事前記録した146ファイルのSHA-256は変更なし。

最初の実行はサンドボックス内のライセンス初期化で失敗し、権限のある独立Unity実行で再試行した。初回の地形検証では寸法検査が同名のAnchorを取得していたため、検査を環境階層に限定して修正した。全景の初回描画はShader初期化の影響があったため、同期コンパイルと事前描画後に再撮影した。最終のUnity batch終了コードは0。

作成用プロジェクトのログにはURPの `TraceRenderingLayerMask.urtshader` に関するリソース読込エラーと、生成コードの旧FindObjectsByType形式への非推奨警告が残っている。地形検証と画像出力は完了したが、エラーログが完全にゼロの実行とはしていない。作成用の描画設定や生成C#は共有プロジェクトへ取り込んでいない。

## 正式起動Sceneへの統合

`BlindSugarRunPlay.unity` は既存 `FlylingualPlay.unity` を複製して作成した。削除対象は旧 `Ground`、本・キー・コーヒー・缶・砂糖・Goal rim等の環境rootだけで、`FlyRoot_Thorax`、`VisualRig`、`BrainIntegration_Optional`、`MockMotorSource`、`WindowsReplayDemo`、`Flylingual Play Services`、`Flylingual Play Screen`、既存Camera/Lightは保持した。新支持Colliderには旧GroundのPhysics Materialと `FlyGroundMarker` をScene overrideで付与している。

起動用Builderは [BlindSugarRunPlayBuilder.cs](../../UnityProject/Assets/BlindSugarRunPrototype/Editor/BlindSugarRunPlayBuilder.cs)、追従Cameraは [BlindSugarRunStageCamera.cs](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunStageCamera.cs)。`PlayScreenBuilder.Build` のBuild対象は新Sceneへ変更され、`EditorBuildSettings`の先頭にも追加された。Windows Buildは29.35秒で成功し、検証記録は `artifacts/blind-sugar-run-startup/build-verified.json` と `build-errors.json` に保存した。31 warningとPipelineの5秒応答timeout 1件が記録されているが、Build自体は成功している。

通常のexeを起動し、Playerログの `BLIND_SUGAR_RUN_STARTED scene=BlindSugarRunPlay` を確認した。Sceneを指定する起動引数は使用していない。検証引数は `-flyConversationNoMicrophone -playScreenProbe <保存先> -playScreenProbeQuit -screen-fullscreen 0 -screen-width 1280 -screen-height 720 -logFile <ログ先>`。コマンドとPIDは [launch.json](../../artifacts/blind-sugar-run-startup/player/launch.json)、受信結果は [report.json](../../artifacts/blind-sugar-run-startup/player/report.json)、集計は [validation.json](../../artifacts/blind-sugar-run-startup/validation.json) に保存した。

Windows実Brain `127.0.0.1:18766`、Unity側Bridge motor `127.0.0.1:18770` の既存起動経路を使用した。60サンプルで `MALECNS_EXPERIMENTAL / LIVE / male-cns:v1.0`、sequence 5→130、fresh 60/60、最大frame age 165.7 ms、probe errorは空だった。一方、神経表示Observerの `ready` は全サンプルfalseであり、ready成功には扱わない。会話セッション開始と音声619,200 bytesの受信を確認したが、マイク入力・身体移動命令・コース通行は検証していない。

非表示PlayerでのScreenCaptureは2回とも失敗し、停止ボタンの可視判定もfalseだったため、Player UIの目視合格には扱わない。別途、Editorで実行時と同じ画角を描画し、[開始地点の画像](../../artifacts/blind-sugar-run-startup/editor-start.png) でハエ・Start Area・定規橋の配置を確認した。この画像はEditorの静止描画であり、実歩行の証拠ではない。

Scene生成時に身体の171コンポーネントのserialization不変、旧環境64 rootの置換、開始位置と支持面高さを検査した。保護対象65ファイルのSHA-256は変更なし（[照合記録](../../artifacts/blind-sugar-run-startup/protected-after.json)）。既存Fly・Brain・会話・音声コードおよび複製元Sceneは保持した。検証Playerは終了し、所有するBrain／Bridgeも `stopped`、使用ポートの待受なしを確認済み。Editorは新Sceneを開いたEdit Modeで、未保存変更なし。

**起動統合時点で未実施：既存Flyの歩行・停止余動・実Brain完走・局所Sensor・Blind UI・ステージ観測を用いた会話・落下復帰・Final Reveal再生。** 落下復帰の追加実装・検証は次節に記載する。環境作成、起動Scene統合、通常exeからの起動は確認したが、Phase 1の通行検証およびPhase 2以降の完了判定は残る。現在の寸法と10〜15分という所要時間は、統合後の実測で調整する。

## ゲームオーバーとリトライ接合

[BlindSugarRunSession.cs](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunSession.cs) は、Fly位置が `y < -2` または `KillVolume` 内に入った時点で状態を判定する。`HasFreshBrain`、`BodyControlActive`、`NativeConversationBody.BodyActive` が揃っている健康な実Brain中の落下は `GameOver`、接続・Brain状態を確認できない落下は `Interrupted` とする。どちらも `EmergencyStop()`、NativeBody無効化、motor source切断、timeScale停止を行う。

[BlindSugarRunGameOverView.cs](../../UnityProject/Assets/BlindSugarRunPrototype/BlindSugarRunGameOverView.cs) は初期非表示の全画面overlayを表示し、本文・挑戦回数・Retryボタンを提供する。クリック直後にボタンを無効化して連打を拒否し、Session側の状態ラッチも二重開始を拒否する。

Retryは同じ `BlindSugarRunPlay.unity` を再読込してFly/CPG/接触状態を初期化する。`ConversationSessionController` とBootstrapは `DontDestroyOnLoad` で保持し、Scene-boundな `NativeConversationBody` と `NativeConversationReaction` は破棄後、新SceneのFlyを参照するインスタンスとして再作成する。Startに配置された新Flyとfresh Brain frameを確認した後、既存 `EnableVoiceActions()` のSTOP/resume経路で再開する。通常Windows exeにはこの接合コードが含まれる。

2026-09-13、通常Windows exeを再ビルドし、実Brain `127.0.0.1:18766`／Bridge motor `127.0.0.1:18770` で物理落下から2回連続のリトライに成功した。診断は開始床のColliderだけを一時的に無効化して重力落下を起こす。身体の移動・motor値の直接注入・Replay・mockは使用していない。再読込で床も元に戻る。診断コードは [BlindSugarRunRetryProbe.cs](../../UnityProject/Assets/BlindSugarRunPrototype/Diagnostics/BlindSugarRunRetryProbe.cs) にあり、Development buildの明示引数時だけ実行される。

- 落下位置は `y=-2.063` と `-2.148`。各回でGameOver、死亡数加算、timeScale=0、身体制御停止、画面表示、1秒間の停止保持を確認。
- 実際のRetryボタンへUI submitを送り、二重リトライが拒否されることを確認。両回とも新Flyが `(0,1.45,0)` に復帰し、新NativeBodyとReactionへ接続。Controllerは同一、各コンポーネントは1個のまま。
- 再開後のTCP sequenceは51→70、122→126。backendは `MALECNS_EXPERIMENTAL`、raw `brainReady` はfalseのままで、ready=trueには扱っていない。2回目の復帰中に既存の `voice_control_stopped_or_stale` が1回記録されたが、既存再接続処理を通って復帰した。通信エラー皆無の試験とはしていない。
- [実測JSON](../../artifacts/blind-sugar-run-retry/player-02/retry-probe.json)、[起動引数](../../artifacts/blind-sugar-run-retry/player-02/launch.json)、[Playerログ](../../artifacts/blind-sugar-run-retry/player-02/player.log) を保存。実RuntimeのUIパネルをRenderTextureへ描画した [ゲームオーバー画面](../../artifacts/blind-sugar-run-retry/player-02/game-over.png) で日本語とボタン表示を確認した。画面全体のOSキャプチャやマウスによる手動クリックではない。

最初の試験では「止めるまで前に進み続けて」の送信後、既存接続監視の停止・再接続が発生してFORWARD適用待ちがtimeoutした（[失敗記録](../../artifacts/blind-sugar-run-retry/player-01/retry-probe.json)）。2回目は `-blindSugarRetryProbeSkipMovement` を明示し、実Brain接続のSTOP状態から落下と復帰を独立検証した。**継続移動中の落下、旧移動命令の持ち越し防止のE2E、音声による再指示、通信断を起こしたInterrupted分岐は未検証。** Goal／Final Reveal／会話への落下記憶利用はこの追加範囲に含めていない。

通常Playerの最終ビルドは成功（[ビルド記録](../../artifacts/blind-sugar-run-retry/build-report.json)）。操作・Brain・物理の既存コードは本作業では変更していない。保護対象80ファイルのうち79はSHA-256不変、並行作業の `NativeVoiceFixtureProbe.cs` だけ変化を検出したが保持した（[照合記録](../../artifacts/blind-sugar-run-retry/protected-after.json)）。

## 接合部のZ-fighting修正（2026-09-13）

歩行経路を連続させるために重ねていた支持ブロックの上面が同じ高さにあり、二重描画されていた。`EnvironmentGeometry`の12支持物について、他のBoxColliderの内部に入る描画面を切り取り、同一平面の重複部分は階層順で後の支持物だけに残した。側面・底面も同じ処理で整理している。描画Meshだけを `SurfaceMeshes/` のアセットへ差し替え、Collider、Transform、Material、支持面高さ、Anchor、既存Fly・操作・Brain処理は維持した。

処理本体は [BlindSugarRunSurfaceMesh.cs](../../UnityProject/Assets/BlindSugarRunPrototype/Editor/BlindSugarRunSurfaceMesh.cs)。既存環境への適用と静的検証は [BlindSugarRunSurfaceRepair.cs](../../tools/authoring/BlindSugarRunSurfaceRepair.cs)。環境の新規生成コードも同じ処理を呼ぶため、再生成時にも重複面が復活しない。Mesh assetのGUIDは再実行時も保持する。Colliderを編集した場合はメッシュを再生成する必要がある。

上面三角形の重複は30組から0組へ減少し、支持面内12,551点で描画の欠落なしを確認した。Collider等のserializationも不変。[初回幾何検証](../../artifacts/blind-sugar-run-surfaces/geometry-first-pass.json) と [最終検証](../../artifacts/blind-sugar-run-surfaces/geometry-validation.json) を保存した。定規橋と分岐を同じカメラから修正前後で静止描画し、接合部の見た目を確認した。初回のMesh複製では描画バッファが更新されず支持面が非表示になったため、Mesh APIによる頂点・三角形・法線・UV・接線の設定に修正している。

正式Windows Playerも再ビルド済み。24.69秒、結果 `Succeeded`、error 0、warning 1（[BuildReport](../../artifacts/blind-sugar-run-surfaces/build-report.json)）。保存したSceneを再読込しても正常に表示されることを確認した。[修正後の定規橋](../../artifacts/blind-sugar-run-surfaces/after-ruler.png)／[修正後の分岐](../../artifacts/blind-sugar-run-surfaces/after-branch.png)。既存コード・Scene等の保護対象81ファイルはSHA-256不変（[照合記録](../../artifacts/blind-sugar-run-surfaces/protected-after.json)）。

この確認は描画・静的形状・ビルドの検証であり、歩行や実Brainの再試験ではない。
