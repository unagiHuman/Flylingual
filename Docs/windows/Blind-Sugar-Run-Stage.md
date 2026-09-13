# Blind Sugar Run 独立プロトステージ

基準：[Astra向け実装指示書](Blind-Sugar-Run-Implementation-Instructions.md)。今回の担当は、別セッションのハエ指示・移動修正と競合しない独立した環境ステージの作成。

## 構成と担当境界

新規配置先は `UnityProject/Assets/BlindSugarRunPrototype/`。環境だけの `BlindSugarRunPrototype.unity` と、後で別シーンへ配置できる `BlindSugarRunEnvironment.prefab` を作る。既存の会話用シーン、Brain、Bridge、CPG、MotorDecoder、Flyの設定、ProjectSettings、Build Settingsは変更しない。

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

生成・検証待ち。共有Editorの解放後に、実際の出力と結果をここへ記録する。
