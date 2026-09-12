# Neural Visualization v1 protocol

この契約は、既存の BrainFrame NDJSON に任意で添付する MaleCNS の神経可視化データを定義する。可視化は観測専用で、Action、motor、CPG、物理、既存のBrain TCP接続を変更しない。`schemaVersion` は整数 `1` 固定である。

## 範囲と同一性

Atlas は `male-cns:v1.0` の graph に存在する実在の MaleCNS `bodyId` と soma 座標を対応付ける。exporter の既定値は最大 **24,000** 点で、上限は **65,536** 点。座標を持たない graph ID は atlas から省略される。atlas は神経突起全体や全脳形状の再構成ではなく、soma の決定論的サンプルである。

`atlasId` は `atlasId` 自身を除いた atlas JSON の canonical JSON（キー昇順、`,` と `:` の separators、NaN 不許可）の SHA-256。Unity は `schemaVersion=1`、`datasetId=male-cns:v1.0`、有限座標、重複しない文字列 ID、64 桁 `atlasId` を検査する。Brain 側はさらに graph `body_ids.npy` の SHA-256 と atlas の `graphIdsSha256` を照合する。照合失敗、atlas 欠落、座標異常は activity を消し、実行を止めずに状態を無効とする。

生成物の標準配置は feature 内の `UnityProject/Assets/BrainVisualization/Resources/BrainVisualization/malecns-atlas.json`。これは生成可能な private asset であり、共有 Scene や既存 serialized asset の変更を意味しない。atlas の source hash、graph hash、`totalGraphNeurons`、`omittedCoordinateCount` は再現性のため保持する。座標変換は表示用の `[sourceX,sourceZ,sourceY]` mapping であり、解剖学的な軸名の主張ではない。

## Incoming BrainFrame

既存の `type=brain_frame` に次の任意フィールドを追加できる。可視化 observer は、同一接続から先に届いた `status` の dataset/instance/session を基準 identity として要求し、その後の frame と一致させる。status が無いまま届いた frame、または identity が一致しない frame は無効である。フィールドが無い場合は voltage-only または telemetry 無しとして扱い、対応 backend が telemetry を出せないときに発火を捏造してはならない。

```json
{
  "type": "brain_frame",
  "sequence": 42,
  "brainTimeMs": 2100.0,
  "metadata": {
    "datasetId": "male-cns:v1.0",
    "backendId": "MALECNS_EXPERIMENTAL",
    "instanceId": "server-instance-uuid",
    "sessionId": "controller-session-uuid",
    "mode": "LIVE",
    "ready": false
  },
  "visualization": {
    "schemaVersion": 1,
    "atlasId": "<64 hex chars>",
    "metric": "window_spike_count",
    "windowMs": 50.0,
    "bodyIds": ["123", "456"],
    "spikeCounts": [3, 0]
  },
  "raw": {
    "bodyIds": [123, 456],
    "deltaV": [-1.25, 0.07]
  }
}
```

`metadata.datasetId`、`metadata.instanceId`、`metadata.sessionId`、`metadata.mode` は incoming visualization の provenance に必須。`mode` は実値を保持し、受入れ試験は `LIVE` のみとする。status の同一 identity の再送は state を reset せず age も更新しない。status identity が変わった場合は activity を clear して新しい session の基準にする。`visualization` がある場合は `atlasId` がロード済み atlas と一致し、`metric` は `window_spike_count`、`windowMs` は正の有限値、`bodyIds` は atlas の順序と同じ長さの canonical decimal **文字列**、`spikeCounts` は非負整数でなければならない。これは窓内の集計値であり、個々の spike event 時刻ではない。

`raw.bodyIds` は既存 raw 出力の数値 MaleCNS `bodyId`、`raw.deltaV` はその同じ順序の現在の VNC 電圧差の subset。atlas に座標が無い ID は raw に残っていても描画対象外となる。ID 重複、長さ不一致、NaN/Infinity、未知 atlas ID、順序逆行は無効扱いとする。同一 sequence の duplicate は無視し、age を更新せず glow も再発火しない。

## Freshness と描画

新規 sequence の受信時だけ frame age を更新する。duplicate frame、heartbeat、status、ack、会話イベントは age を更新しない。750 ms を超えたら glow と activity を clear する（実装の serialized stale 値は `0.1..0.75` 秒に clamp）。atlas ID mismatch、identity mismatch、disconnect、protocol error、telemetry 無しも clear する。Glow の値は窓集計または deltaV からのみ計算し、未観測点は発火していないと解釈しない。

Unity 側は既存の単一 `BrainTcpClient` の `ReceivedLine` event にだけ購読する。可視化 component は新しい TCP 接続、controller、送信、Action、input routing、再接続を追加しない。feature は既存 client の接続前に enable する。接続後に追加する場合は Windows owner が controlled reconnect を行う。`ReceivedLine` は worker thread から最大4件の queue に入り、各 `Update` で最大1件の neuron frame を適用する。queue overflow や適用を飛ばした window は drop として数えるだけで、データを補間・捏造しない。Unity API と JSON 解釈は main thread で行う。

点群は custom GPU batched quads と既存 shader を使用する。VFX package は追加しない。生成 prefab は off-world の `AnatomicalDisplay` と layer **31**、可視化専用 orthographic camera（RenderTexture）を使う。gameplay camera、lighting、physics、入力を変更しない。GUI mouse drag は GUI の orbit 操作だけを消費し、gameplay input の抑止を意図しない。この境界は Windows 実環境での操作レビューで再確認する。

## Compatibility and measurements

Bridge v1 の既存 BrainFrame payload を保持したまま、可視化 field を additive に送る。旧 consumer は未知 field を無視できる。可視化を有効にしたときは frame payload サイズ、JSON parse 時間、queue drop、Unity main-thread処理時間、GPU/CPU/RSSを計測する。24,000点の atlas と最大4行 queue がメモリ負荷を増やすため、memory/payload overhead の実測を必須とする。

この契約は、backend が真の spike telemetry を供給することを保証しない。backend の atlas 読み込み失敗は worker 初期化失敗となり、server error として扱う。Unity の atlas 読み込み失敗は visualizer だけを無効化し、既存 Brain 接続や gameplay を停止しない。telemetry 非対応 backend、固定 replay、mock、推測した発火値は、Neural Visualization の LIVE acceptance の証拠に数えない。
