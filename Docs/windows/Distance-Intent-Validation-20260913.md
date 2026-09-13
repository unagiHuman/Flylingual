# 距離指定と大まかな移動の検証

2026-09-13。対象は通常の `artifacts/windows-native-conversation/unity/FlylingualConversation.exe`、Windows Brain `127.0.0.1:18766`、LIVE / MALECNS_EXPERIMENTAL / ready=false。既存刺激→神経→decoder→motor→CPG/PhysXを使用し、位置・motorの直接指定、Replay、mockによる身体の代替は行わない。仕様は[距離指定](../integration/Distance-Intents.md)。

## 解釈

実Responsesで8ケースを1回ずつ実行し、8/8が期待した構造化意図へ変換された。対象は約5m、500cm、半メートル、ちょっと前へ、もう少し前へ、現在動作であと2m、右を向いて5m、時間と距離の併記時の確認要求。応答時間1.704〜2.719秒、既存8秒の意図有効期限内。

[原本・source/config hash](../../artifacts/distance-intents/classification-01/report.json)。本結果は言語解釈のみであり、身体の停止距離やマイク認識の証拠ではない。

```powershell
$distanceStack = Get-Content Runtime/Config/windows-stack.local.json -Raw | ConvertFrom-Json
.venv-bridge/Scripts/python.exe tools/verify_persistent_intents.py --output artifacts/distance-intents/classification-01 --key-file $distanceStack.keyFile --case distance_approximate_five --case distance_centimeters --case distance_half_meter --case distance_little_forward --case distance_little_more_forward --case distance_continue_two --case distance_right_then_forward --case distance_conflicting_duration
```

## 身体連動の途中結果

実テキスト入力を既存Responsesへ送り、UnityからBrainFrame受信、距離進捗、通常STOP、次の指示の待受を記録した。マイクは試験引数で無効にした。

| 試験 | 結果と修正 |
|---|---|
| normal-01 | 起動時に必要port占有のエラー。70.469秒で未完了。未知PIDを停止せず、所有PID・portは終了時解放。 |
| normal-02 | 5.031mでSTOP要求、312ms後にBrain適用。UnityのJSON nullが空のactiveExecutionオブジェクトとなり、終了検出が不成立。executionIdの空文字も無効として修正。 |
| normal-03 | 3ケースの移動・通常STOP・待受が成立。ただし到達後の余走が大きく、5mは最終水平変位6.181m、0.5mは1.535m。旧probeのPASSは操作経路のみで、距離精度の合格として扱わない。 |

各原本: [normal-01](../../artifacts/distance-intents/normal-01/runner-metadata.json)、[normal-02](../../artifacts/distance-intents/normal-02/runner-metadata.json)、[normal-03](../../artifacts/distance-intents/normal-03/runner-metadata.json)。Player例外はいずれも0、残留所有PIDなし。normal-03は壁時計30.766秒、peak process-tree RSS 1,154,666,496 bytes。

余走対策として、実速度からの早期STOP、身体の停止観測、停止後の最終距離判定を追加。probeもmotorだけでなく実速度0.03m/s未満の0.5秒維持を確認し、最終距離の許容範囲を独立に記録するよう更新した。

ユーザーの最新方針により、停止位置の厳密一致を追い込まず「指示を解釈して進み、次の入力を受け付ける」を優先する。最終probeの通常距離ケースの操作経路PASSは、正しい距離で受理、実移動が目標の半分以上、距離終了理由が到達/過走/不足のいずれか、停止と待受の成立を条件とする。`distanceWithinTolerance` と誤差は別に保存し、過走や不足を精度合格へ書き換えない。

## 最終確認

余走対策版 `normal-04` は3ケースの操作経路PASS。距離精度は2ケース中1ケースが許容範囲内であり、短い移動の過走は既知の残課題として保持する。追加の精度調整は行わない。

| 入力 | 最終実測移動距離 | 結果 |
|---|---:|---|
| 5mぐらい前に進んで | 4.546m（目標との差 -0.454m） | 移動、通常STOP、次の指示待受を確認。許容0.5m内。 |
| ちょっと前へ | 0.901m（解釈目標0.5mとの差 +0.401m） | 移動、通常STOP、待受を確認。許容0.15m外をdistance_overshoot/未完了として記録。 |
| 5mぐらい前に進んで → 止まって | 3.376m | 次の言語指示で中断して停止、待受を維持。停止入力の送信後もAPI/Brain/身体の応答待ちによる移動あり。距離精度の母数から除外。 |

```powershell
.venv-bridge/Scripts/python.exe tools/verify_distance_player.py --output artifacts/distance-intents/normal-04
```

[測定原本](../../artifacts/distance-intents/normal-04/report.json)、[hash・環境・Bridge証拠](../../artifacts/distance-intents/normal-04/runner-metadata.json)、[終了時画面](../../artifacts/distance-intents/normal-04/screen.png)。画像は終了時の画面であり、連続した歩行映像ではない。親が画面と距離標本を確認した。

BrainFrame 177件、sequence 2→178、最大受信間隔344ms。Brain窓計算の中央値130.563ms、最大287.162ms。Brain command applied E2Eは中央値219ms、最大359ms（起動/終了のSTOPも含む）。stale_brain / brain_transport_errorによるinhibitは記録なし。backend/readyは前述どおり。壁時計34.796秒、peak process-tree RSS 1,153,036,288 bytes、Player例外0、残留所有PIDなし、使用port解放済み。

実マイクによる今回の距離発話は未実施。関連Python112テストが4.321秒で合格、抽出された現在の意図変換モジュールもHTTP境界16テストが0.967秒で合格。これらはネットワークを使わない制御・翻訳契約の確認であり、身体の検証とは分ける。

ビルドは停止中の対象Unity EditorへUnity CLIからRefresh/コンパイルを要求し、scriptCompilationFailed=falseを確認して通常Playerを作成。旧uloopを前提とするsafe-compile補助スクリプトは利用できず、接続済みEditorのコンパイル確認を用いた。神経モデル・decoder・物理設定の変更はない。commit/pushは行っていない。
