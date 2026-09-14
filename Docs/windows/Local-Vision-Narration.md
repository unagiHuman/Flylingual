# 局所視界からのハエの説明

2026-09-14。Blind Sugar Run用。身体操作の既存6 Action → Windows Brain → BrainFrame → CPG/PhysXは変更しない。

## 動作

- ハエ周辺の最大3mを、ミニマップと共通の局所Physics観測から説明する。全体地図や正解ルートはGPTへ渡さない。
- 方角はハエの正面を基準に8方向。未観測・遮蔽・古い観測は不明とする。「障害物が検出されない」を通過保証にしない。
- 定規、本、皿、砂糖などは、実際に観測したColliderの種別だけを利用する。視認部分から物体全長・ルート接続先を取得しない。
- 発話は危険、新しい物体、足元を優先し短くまとめる。同じ説明は繰り返さず、通常の自発発話を間引く。
- 「周りには何が見える？」「右は危ない？」「前に何がある？」などは最新視界を確認して返答する。質問処理はActionを発行しない。混在する移動指示は既存の解釈経路へ渡す。
- 「1」の全景デバッグ表示は観測半径を変えない。探索記録と現在観測は別に扱う。

## 境界

`BlindSugarRunExplorationMap` → `BlindSugarRunLocalVision` → `BlindSugarRunVisionPublisher` → 既存`ConversationSessionController`のcontrol WebSocket → `LocalVisualObservation` → 既存GPT Live会話。

視界は外部センサーによる観測であり、MaleCNSがUnity映像を認識したとは扱わない。画像認識・追加モデル・新しいBrain接続は導入しない。

新しいcapabilityは`local_visual_observation_v1`、イベントは`local_visual_observation`。既存の`local_safety_observation`やmotor契約を変更せず、説明用データを追加する。

| フィールド | 内容 |
|---|---|
| controlEpoch / conversationGeneration / sequence | 世代と順序。古い観測の利用を防ぐ |
| ageMs | 送信待ち時間を含む観測年齢。750msで失効 |
| facts.ground | 観測した足元の種別 |
| facts.moving / stable / revisited | 実際の身体状態と、過去に通った領域への再訪 |
| facts.directions | 8方向の観測。surface / distance / edge / edgeDistance / trend / alignment / slope |

種別・方向・状態は許可リストで検証する。距離は-1（不明）または0〜3m。自由文、絶対座標、全体経路は含めない。更新は5Hz、送信待ちが混んでいる場合は観測を間引く。

## 検証用起動

通常のWindows Playerに`-blindSugarVisionProbe <出力先>`を指定すると、実Brain/GPT Liveで観測受信、3つの文字質問、その後の明確な1m前進命令を検証し終了する。`-flyConversationNoMicrophone`を併用し、実マイクを収録しない。

この診断に限り、3つの回答を待てるようハエたたきの待機時間を120秒にする。通常プレイの20秒ルール、身体、地形は変更しない。診断は本文を含む結果を指定出力先へ保存する。通常プレイの会話本文ログは追加しない。

## 2026-09-14の検証結果

- Unity 6000.5.9f1でコンパイル成功。通常Windows版ビルド成功、errors=0 / warnings=36 / 22.54秒。
- Python 3.10.12。`python -m unittest tools.test_local_visual_observation tools.test_stale_observation_errors -v`で13項目成功。視界の型、750ms失効、距離範囲、方向の独立性、新物体の優先、重複発話、英日質問と混在命令、既存の古い観測エラー処理を確認。
- 通常Playerを `-flyConversationNoMicrophone -blindSugarVisionProbe artifacts/blind-sugar-run-vision/player-01` 相当の絶対パス引数で起動。Windows実Brain `127.0.0.1:18766`、Bridge motor `18770`、control `18771`、backend `MALECNS_EXPERIMENTAL`。固定Replay/mock/身体位置の直接操作は使用していない。
- 実測1起動。Brain sequence 33→312、fresh 151/151サンプル。受信したreadyは`false`のまま記録しており、接続成功によって昇格していない。Controllerのerror/schema errorは空。
- 視界送信160回、受信ACK156回（計測購読開始前の送信を含むため同数ではない）。3つの文字質問すべてで返答ACKを受信し、Action送信件数・適用request IDが不変。質問中の位置差は最大約0.0000002m。
- GPT Liveの字幕と非無音音声データ1,449,600 bytesを受信。音声入力は無効であり、実マイク認識や人による音質評価の合格を意味しない。
- その後の「前に1m進んで」で約0.798mの実移動を確認。本試験は質問後も移動できることの確認であり、1m距離精度の合格とはしていない。
- 診断終了後、所有Player/サービスが正常終了。通常プレイのハエたたき時間は20秒のまま。

証拠は`artifacts/blind-sugar-run-vision/`の`build-report.json`、`provenance.json`（source/config SHA-256）、`player-01/report.json`、前後の`local-facts-*.json`、Player log。今回の診断ではBrainデータ本体hash、RSS、各回答の音声完了E2Eを採取していない。

未確認: 定規橋全区間、実崖への接近、遮蔽物・再訪・全景トグルの各組合せの実プレイ、実マイク入力。初期チュートリアル発話が質問返答に続く場面があるため、最終的な発話間隔・聞きやすさの調整は残る。データ検証の成功をこれらの実測成功に読み替えない。
