# FlyVisual Realism — session candidate

2026-09-12。既存のハエの外観を改良した候補アセット。後続の接地修正は別のUnity候補Sceneへ保存する。プロジェクト全体の設計ルールを追加する文書ではない。

## 開くファイル

- `FlyVisual_Realism.blend`: Blender 4.2.2 LTSの編集原本。体、眼、翅、脚、材質、画像を含む。画像はpack済み。
- `Assembled_Existing_Rig_ReferencePose` collection: Unityの既存ピボットから取得した6脚の表示用組立。アニメーションや追加のArmatureは持たない。
- `Segment_Library_NOT_BODY` collection: 既存ピボットへ取り付けるCoxa/Femur/Tibia/Bridgeの4メッシュ。初期表示・レンダリングは非表示。編集時にcollectionを表示する。
- Unity外観比較: `Assets/VisualDemo/SessionRealism/FlyRealismDemo.unity`。従来のSceneを保存変更せず、外観候補として分離している。
- Unity接地修正版: `Assets/VisualDemo/SessionRealism/FlyGroundedRealismDemo.unity`。骨格数・階層・ローカル長さ・Collider寸法を保持し、脚の基準姿勢と候補専用の歩行設定を修正したScene。

## 改善内容

胸腹部の輪郭と浅い背板、暗い腹端、滑らかな翅と細い翅脈、触角・口器・平均棍、方向を付けた毛、先細りの脚と足先を制作した。六角小面、体表の色・法線・粗さ、翅膜の透過を9枚の画像へ記録し、UnityのURP/Litへ接続する。

脚への追加フィードバックを受け、付け根・太もものふくらみ、滑らかな太さの変化、控えめな湾曲、丸い関節端を再調整した。最終セグメントの末端41%は5節の足先として作り、細い接続部と小さな爪を表現する。節は表示形状であり、可動ボーンを追加しない。既存リグによる脚の開き方や関節角そのものは保持する。

外観比較候補では元の18関節、6 FootPad、25 bindings、表示ピボットと物理側の計算を維持する。身体の6オブジェクト名と原点は元 `.blend` から採取し、FBXの軸設定も元生成処理と合わせている。各脚メッシュはUnityのローカル+Z、始点0・終点1の契約で出力する。

## 再生成

作業時は公式Blender 4.2.2 LTS (`c03d7d98a413`) を使用した。任意のOSで同版のBlender実行ファイルへ読み替える。

```text
blender --background --factory-startup --python ArtSource/Blender/SessionRealism/generate_realism.py
```

`generate_realism.py` は元 `ArtSource/Blender/FlyVisual.blend` を読み取り、候補の `.blend`、`Assets/FlyVisual/SessionRealism/` 配下の2 FBX・9 PNG、セッション成果物のプレビュー・生成記録だけを書き出す。元モデル用 `generate_fly.py` は実行しない。`-- --skip-render` で確認画像の生成を省ける。

表面画像は `generate_surface_textures.py` の `generate(output_dir)` で生成する。固定seed、Python標準ライブラリとnumpyだけを使用する。Body atlasの下側領域は頭・胸・脚、上側領域は腹部。MaskはR=Metallic(0)、G=AO、B=0、A=Smoothness。NormalはOpenGL tangent space、BaseColorはsRGB。

`rig_reference_pose.json` は旧Sceneから取得した表示用配置と元Sceneのハッシュ。Blenderの全身確認にのみ使用する。実行時の追従はUnityの現行Mapperが担当する。物理Sceneを別作業で変更した場合は、全身確認用の配置も現物と照合する。

Unityのメニュー `FlyBrain > Visual Realism > Create Candidate Scene` で、画像の取り込み設定、候補専用6マテリアル、既存Mapperへの取り付け、候補Sceneを再生成できる。同メニューに中立照明/ゲーム照明の比較画像とMac Playerの作成入口がある。元Sceneと元マテリアルは更新しない。

Unityが保存時に再計算する関節のparent anchorは、他のArticulationBody項目が一致することを検査してから、元Sceneの記述精度を候補へ保持する。物理側のプロパティ変更は行わない。

## 出典と制限

形状とテクスチャはこのプロジェクト用にローカル生成した。外部mesh・textureの組み込み、画像生成API、外部アップロードは使用していない。形状参考は [CSIROの解剖アトラス](https://www.ento.csiro.au/biology/drosophila/melanogaster.html)、[FlyBase頭部図](https://flybase.org/reports/FBim0000765)、[FlyBase胸部・翅の図](https://flybase.org/reports/FBim0000853)。資料画像の転載はしていない。

脚の輪郭と太さの差は[一般的なショウジョウバエ3Dモデルの公開プレビュー](https://www.turbosquid.com/3d-models/drosophila-melanogaster-fruit-fly-obj/576944)をブラウザーで確認した。足先の5節構成は[解剖学的ランドマークに基づく脚モデルの論文](https://pmc.ncbi.nlm.nih.gov/articles/PMC11233710/)を参照した。モデル本体の購入・ダウンロード・流用は行っていない。

ショウジョウバエを参考にした表示モデルであり、実測の解剖再構築やMaleCNS標本の同一個体モデルではない。外観比較候補だけでは既存の接地姿勢・歩行能力を変更しない。後続の接地修正版の範囲は下節を参照する。Blenderの静止画は実際の歩行や接地を証明しない。

検証の実測結果と画像・映像は、対象セッションの `artifacts/sessions/01a09446-1c64-74c1-8579-f133826d2dd2/` に保存する。

## 接地修正版の再生成

Unityメニュー `FlyBrain > Visual Realism > Create Grounded Candidate` は外観比較Sceneから接地修正版と専用Configを生成する。足先は膝より下へ向け、左右の関節角を鏡映し、接地中は足を前から後ろへ送る。停止時は全脚を支持状態へ戻す。FootPad表面の表示補正はVisualRigだけで行う。原本の共有Sceneと共有Configには適用しない。

`Build Grounded Candidate OSX` でMac用Playerを生成できる。Blenderファイル中の全身組立は従来の基準姿勢で、接地修正版の実行姿勢を保存したアニメーションではない。新しい姿勢・接触の確認には接地修正版Sceneとセッションの `Fly-Grounded-Stance-Validation.md` を使う。
