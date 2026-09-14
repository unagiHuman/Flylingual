# 通常Windows Playerのハエ叩き例外を解消

2026-09-14。ユーザーが起動した通常版の更新漏れを修正し、同じexeで実Brain試験を通過した。

## 原因と対応

通常起動先 `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` のAssembly-CSharp.dllは00:51 JST版だった。検証用Dev-Localだけが22:00版になっており、通常版へ既存修正が反映されていなかった。

保存した旧Playerログは `artifacts/windows-build-fix/before-player.log`。最初はBuildPresentationでshader=nullのArgumentNullException、その後UpdateのNullReferenceExceptionが7,852件。既存ソースにはResources/IdleSwatter.shaderの同梱、null検査、表示初期化の分離が既にあるため、ゲームコードの重複修正は行っていない。

対象Playerを通常終了し、`NativeConversationBuilder.Build()` で通常起動先を再生成。22:13:37→22:13:49 JSTにSucceeded。BuildReportのCLI応答5秒timeoutはビルド失敗と区別した。新dllは22:13:48 JST。検証runnerに `-NativePlayer` を追加し、今後通常版を直接検査できるようにした。既定のDev-Local出力先は維持する。

## 実Player検証

```powershell
& tools/neural_player_trial.ps1 -Name native-swatter-fix -Language ja -Question 0 -ConnectionStability -NativePlayer -RenderScreenshot
```

通常版exe、Windows Brain 127.0.0.1:18766、MALECNS_EXPERIMENTAL／LIVE、ready=false、実GPT Live/API、マイクなしの固定テキスト。設定は終了時に復元。

- connection_stability_pass、error空、fresh=true、STOP適用、質問後再移動1.901m。
- 制御喪失0、epoch変化0、Player seq20→267、265frames／264neuralFrames。
- 警告1／回避1、果汁接触1、感覚ON3窓／OFF9窓。
- PlayerログのException 0、PRESENTATION_UNAVAILABLE 0。元のshader欠落と反復NREの再発なし。
- Unity frame p95 16.921ms、Player sampled peak RSS 641,953,792 bytes、exit 0。

原本は `artifacts/neural-feedback/native-swatter-fix*`。ソースと通常版dllのSHA256は `artifacts/windows-build-fix/source-build-hashes.json`。Brainの数値・設定・graphは [直前の検証](../integration/Transient-Subnormal-Latency.md) と同じで今回は変更なし。

D3D12のinfo queue問い合わせ失敗という起動診断行は残る。今回の対象例外とは別で、描画・操作試験は通過。マイク・音響品質・全ステージ通しプレイを完了したとの主張はしない。生成されたexeはGit管理外なので、pushだけでは他端末の古いexeは更新されない。
