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

**未実施：既存Flyの歩行・停止余動・実Brain完走・局所Sensor・Blind UI・ステージ観測を用いた会話・落下復帰・Final Reveal再生。** 環境作成、起動Scene統合、通常exeからの起動は確認したが、Phase 1の通行検証およびPhase 2以降の完了判定は残る。現在の寸法と10〜15分という所要時間は、統合後の実測で調整する。
