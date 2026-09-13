# 距離指定の移動意図

2026-09-13。距離指定は既存の 6 Action、Bridge、MaleCNS、decoder、CPG、Physics の経路を変えずに、Bridge が実行終了を管理する意図拡張である。契約は [distance_intents_v1](../../Contracts/bridge-v1/distance-intents-v1.md) を正本とする。本書は振る舞いと受入れ条件を説明し、実装・実測の完了を示すものではない。

## 使える指示

- 「5mぐらい前へ」「500cm進んで」「半メートル前へ」は、それぞれ距離を metres に正規化する。
- 「ちょっと前へ」は 0.5 m の新規 FORWARD、「もう少し前へ」は移動中なら現在 execution の更新時点から追加 0.5 m、移動中でなければ新規 FORWARD 0.5 m とする。
- 「そのままあと2m」は現在位置からさらに 2 m とする。`inherit` と条件追加は起点・目標距離・残距離を保持する。
- 明確な時間と距離を同時に指定した場合は初版では `clarify` とし、優先順位を推測しない。

距離は 0.05〜100 m のみ受理する。距離が使えるのは `FORWARD`、`FORWARD_R`、`FORWARD_L`、および `forward_until_concern`、`right_then_forward`、`left_then_forward` だけである。純粋な旋回、nudge、STOP には距離を指定できない。右／左を向いてから前進する plan では、距離計測は前進 phase の開始から行い、旋回中の移動を目標へ加えない。

## 距離の観測と終了

Unity は既存 `local_safety_observation` に任意の `travelMeters` と `horizontalSpeedMetersPerSecond` を載せる。前者は epoch と conversation generation ごとにリセットする水平累積距離、後者は有限かつ 0 以上の水平速度であり、不明値はともに `-1` とする。距離実行の admission には fresh な距離と速度の両方が必要である。旧 payload は距離を使わない既存操作だけで互換とする。

距離は 1 cm 以上の水平区間を積算し、静止時の jitter と上下動を除く。STOP 後も実速度が 0.03 m/s 以上なら積算を続ける。未観測の目標進捗を Bridge や会話側が捏造してはならない。ここでの逆行は走行方向の後退ではなく、累積 counter が巻き戻る不正な観測を指す。

`activeExecution.distancePhase` は `moving` または `braking` である。Bridge は実速度×1.2 秒を初期余走見込みとして、目標の直前で通常 STOP を出して braking へ移る。到達は STOP 適用後、速度が 0.03 m/s 未満、距離が 0.5 秒安定した時点で最終実測する。許容誤差は `min(0.5, max(0.15, 0.1 * targetDistanceMeters))` m、かつ実移動が `min(0.05, targetDistanceMeters * 0.5)` m 以上の場合だけ `distance_reached`／`completed=true` とする。距離は approximate であり、5 cm の精密停止を保証しない。

過走は `distance_overshoot`、不足は `distance_shortfall` として未完了にする。停滞（8 秒間で 0.02 m 未満）と 300 秒上限も未完了であり、終了理由はそれぞれ `distance_stalled` と `distance_timeout` である。STOP 確認は最大 10 秒で、未適用 STOP または送信失敗は既存 inhibit とする。いずれの未完了でも自動再前進しない。危険、距離または速度の欠損、counter 巻戻り、jump、epoch fault は既存 inhibit の対象であり、距離機能で緩和しない。

`command_result` の `execution_finished` は `completed`、`targetDistanceMeters`、`traveledMeters`、`remainingMeters` と終了理由を返す。`bridge_state.activeExecution` は同じ距離進捗と `distancePhase` を公開する。これは Brain 適用または身体の任意移動を偽装するための値ではない。

## 検証状況

Windows通常Playerと実Brainで、約5mの移動、「ちょっと前へ」、次のSTOP指示と待受の3ケースを確認した。実測はそれぞれ4.546m、0.901mで、短い移動の過走は残る。ユーザー方針に従い、操作を受けて進むことを優先し、停止位置の精密調整は行わない。言語解釈は実API8ケース、制御は関連112単体テストで確認。今回の実マイク試験、100m全行程、すべての地形・旋回組合せは未検証。[試験条件・原本・残課題](../windows/Distance-Intent-Validation-20260913.md)を参照する。
