# 有限時間の静止→CPG合流診断（2026-09-12）

## 判定

本番採用しない。補間は所定時間で終了するが、FORWARD_Lの逆旋回を除去せず、悪化する初期位相を移動した。Gameplay gateは未通過。

## 実装範囲

FlyLocomotionControllerに非SerializedのDiagnosticJoinSeconds（既定0＝OFF）を追加。activityがgaitStartThresholdを越えた時点の各関節drive targetを保存し、0.64秒で現在のnominal targetへ合流する。入力Action名は参照しない。CPG位相、stance判定、Brain、decoder、adhesion、関節limit、ゲーム用assetは変更していない。

今回の診断は初期target速度0の静止開始専用。q=(1-w)q0+w*qNominal(t)、w=6u^5-15u^4+10u^3。計画の未来targetを固定するHermite方式とは異なり、motor平滑化中のnominalを追いながら締切を固定する限定実験。任意速度からのC1接続、方向反転、STOP遷移、接地による脚選択は未実装。nominal/clamp自体の不連続を解消するものでもない。

## 検証

- Unity 6000.5.5f1、Windowsビルド終了コード0。
- 既存28,800件のnominal target回帰比較：誤差0、stance一致。
- 固定Replay、保存済み初期状態、FL/FR×位相0/90度×3回、8秒、計12試行。
- Player終了コード0。今回ログでerror CS/Exception:該当なし。
- 全28,800脚サンプルで独立したログ再計算を実施。補間誤差最大0.00003792度、締切後nominalとの差最大0.00003149度（許容0.001度）。最初の記録t=0.02で補間elapsed=0、t=0.66で通常targetに到達。
- fallは1/12。joint clampは3,384脚サンプル。接触を改善したという判定はしない。

右旋回を正とする。各3試行の平均yaw（度）：

|入力/初期位相|従来baseline 2秒|今回2秒|今回8秒|
|---|---:|---:|---:|
|FORWARD_L / 0|−52.90|+45.64|+192.95|
|FORWARD_L / 90|+53.98|−39.94|−222.21|
|FORWARD_R / 0|+48.32|+18.09|+91.06|
|FORWARD_R / 90|+32.98|+32.38|+177.18|

FL位相0は3/3で2秒時点の逆旋回。FR位相0も0.5秒平均−1.64度と初動が逆。baselineは既存coxa-check/baselineからの比較で、同一バイナリ同時収集ではない。FLとFRはturn絶対値が異なるため、完全な鏡像条件とは扱わない。

## 証拠と保存先訂正

artifacts/windows-malecns/finite-join/{body.csv,legs.csv,contacts.csv,summary.json,transition-verification.json,Player.log}。
ビルドログはartifacts/windows-malecns/finite-join-build.log。

初回runnerの保存先置換漏れで、過去のseparate-steering生ログを上書きした。今回データは処理完了後finite-joinへ移動した。separate-steeringは既存条件で12試行を再取得済みであり、現在の生ログは過去レポートの元データではない。過去集計レポートは保持。新runnerは既存出力ディレクトリがあれば停止する。

## 次段階

開始補間だけでは不十分という結果を保持し、接地観測の時刻・取得元を揃えたうえで、stanceと軌道の整合を別実験で評価する。非Foot接触もあるためFootPad情報だけで支持が成立しているとは判定しない。物理原因を一意に特定したとは主張しない。

## 今回変更ファイル

- UnityProject/Assets/FlyLocomotion/FlyLocomotionController.cs
- UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.cs
- tools/run_finite_join_diagnostic.py
- tools/verify_finite_join.py
- 本レポート

SerializeField追加・変更なし。commit/pushなし。
