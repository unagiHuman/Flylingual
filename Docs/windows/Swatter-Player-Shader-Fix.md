# Windows Player のハエたたき例外修正（2026-09-14）

実行中の Player（PID 43844、09:58:29 起動）の Player.log で、最初に `BuildPresentation` の `new Material(null)` による `ArgumentNullException: shader`、続いて Update の未生成 warningLabel による NullReferenceException が反復していた。過去ログだけの問題ではなかった。

`BlindSugarRunIdleSwatter.cs` は、Resources 内の専用 `IdleSwatter.shader` を読み込むよう変更。Shader.Find だけに依存したビルド時の欠落を解消する。UI・音・形状は個別に一度だけ初期化し、演出失敗時も警告を一度記録して死亡判定へ進める。ラベル更新は形状の有無から独立させた。20秒の条件と身体制御は変更しない。

確認結果:

- Unity Editor コンパイル完了、コンパイルエラーなし。
- Brainへ接続しないプレビューシーンで実コンポーネントの表示生成を実行。ラベル生成、形状15部品、シェーダー対応・エラーなし、再初期化で重複しないことを確認。初回CLIは5秒タイムアウト、再実行は成功。
- Windowsビルド Succeeded（10:06:05〜10:06:51 JST）。DetailedBuildReport に `Assets/Resources/IdleSwatter.shader` が梱包されたことを確認。
- build summary は warning 36 / error 1。error の原文はビルド中に問い合わせた Pipeline の `Main thread operation timed out after 5000ms` のみ。ゲームコード・シェーダーのビルド失敗ではないが、エラー0とは報告しない。
- 出力: `artifacts/windows-swatter-fixed/unity/FlylingualConversation.exe`。
- ユーザー指定に従い、起動中の旧Playerとその所有サービスは停止・上書きしていない。新Playerの実プレイ検証は未実施。旧Player終了後に上記修正版を起動して警告・死亡・Retryの実プレイ確認が必要。

証拠は `artifacts/swatter-build-fix-20260914/` 内の original-error.txt、presentation-result.json、build-result.json、build-errors.json。コミット・プッシュは実施していない。
