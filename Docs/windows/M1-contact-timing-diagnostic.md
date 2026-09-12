# 接地・stance処理順の診断（2026-09-12）

## 結論

CPGと吸着処理の実行順が脚によって異なることを確認した。診断時だけ全脚の吸着をCPG target適用後に実行するとstance不一致は930/28,800脚サンプルから0になった。しかしFORWARD_Lの位相90度における逆旋回は3/3で残る。処理順の統一だけでは解消しない。本番既定は変更せず、Gameplay gateは未通過。

## 観測と実装

- FlyFootAdhesionに、実際に消費したstance/contact/hold ticksと評価fixedTimeを読み取り専用で追加。
- Controllerのtarget適用直前と、物理ステップ後にsupport.csvを記録。lastContactFixedTime、age、取得元、freshness、法線、位置、吸着力、関節targetを保存。
- 従来条件ではLF/RF/RMがCPGより先に吸着を評価し、LM/LH/RHは後に評価。切替時に前のstanceが混入していた。
- DiagnosticDrivenByController（非Serialized、既定false）を診断flagから有効にした場合のみ、通常の吸着FixedUpdateをスキップし、全脚target適用後に同じ計算処理を1回呼ぶ。
- CPG計算式、phase、関節limit、摩擦、吸着強度、BrainFrame、decoderに変更なし。前回の有限補間もOFF。

## 試験

Unity6000.5.5f1、Windows Standalone。最初の観測12試行に続き、処理順統一12試行と同一ビルドの従来条件12試行、計36試行。各条件FL/FR×位相0/90×3、8秒。保存済み初期状態、固定Replayを使用。

比較対象はcontact-timing-controlとordered-adhesion。後者だけ-diagnosticOrderedAdhesionを指定。各28,800脚サンプルについて適用前/物理後のfixedTimeと脚IDの対応を検査し、欠落なし。吸着は物理後の全サンプルで同じfixedTimeに評価済み。

|条件|従来2秒yaw平均|処理順統一2秒yaw平均|
|---|---:|---:|
|FORWARD_L / 0°|−44.31°|−45.68°|
|FORWARD_L / 90°|+54.45°|+53.64°|
|FORWARD_R / 0°|+46.63°|+49.41°|
|FORWARD_R / 90°|+36.26°|+37.38°|

正は右旋回。各平均n=3。fall判定は従来2/12、統一1/12であり、改善の統計的主張はしない。FLとFRのturn絶対値は異なるので鏡像条件ではない。

## 初動の接地

最初の25物理tick（0.5秒）、3試行×6脚＝450脚サンプルで比較。

統一後FL位相90°はattached=0/450。fresh接触はLM15、RM18、その他4脚は0。FL位相0°ではattached=12/450、fresh接触はLM37/RF15/RM20/RH21。phaseにより接触する脚と時刻が変わる。

統一後FL位相90°の初動に記録された非Foot colliderの法線impulse合計はLM_Tibia約6.90、RF_Tibia約2.89、RM_Tibia約2.75 N·s（3試行分）。足裏だけで支持を判定する設計は現状と合わない。取得元はARTICULATION_OWNERであり、保持された速度はownerの線速度であって接触点相対速度ではない。

重要な限界：freshは保持期限内の接触観測であり支持力ではない。contactの接線impulse観測が不足しているため、この法線impulse集計でyawトルク収支を閉じたとは言わない。重複の可能性があるcallback集計を正確な全外力へ置き換えない。処理順だけでなく非Foot接触と関節追従を次の切り分け対象にする。

support.csvのtはTime.fixedTime-started、既存body.csvのtはtick数×0.02。最初のtickは前者0/後者0.02であり、同じサンプルを結合する場合はtick順で合わせる。初動集計は浮動小数の境界誤差を避け各脚先頭25行を使用。

## 検証・保存先

- ビルド2回とも終了コード0、nominal target回帰28,800件で誤差0。
- Player3回とも終了コード0。例外検査はPlayer.log/ビルドログのerror CS、Exception:検索。
- artifacts/windows-malecns/contact-timing：最初の観測。
- artifacts/windows-malecns/contact-timing-control：同一ビルド従来条件。
- artifacts/windows-malecns/ordered-adhesion：診断候補。
- 上記各フォルダsupport.csv、body.csv、legs.csv、contacts.csv、summary.json、contact-timing-summary.json。
- artifacts/windows-malecns/contact-timing-comparison.json。
- 比較2条件にrun-manifest.json（実行引数、開始UTC、ソース/Player hash）。Assembly-CSharp.dllは両試験終了後に採取したpost-run-assembly-hash.json。間に再ビルドなし。

再実行：専用venvのpythonでtools/run_contact_timing_diagnostic.pyまたはtools/run_ordered_adhesion_diagnostic.py。--outputで新しい保存先を指定する。既存ディレクトリには書き込まない。集計はtools/analyze_contact_timing.py <出力ディレクトリ>。

## 変更ファイル

FlyLocomotionController.cs、FlyFootAdhesion.cs、FixedPhysicsDiagnostic.cs、tools/run_contact_timing_diagnostic.py、tools/run_ordered_adhesion_diagnostic.py、tools/analyze_contact_timing.py、本レポート。SerializeField変更なし。未commit、未push。
