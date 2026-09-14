# 視覚危険入力の実Brain下流応答検証

2026-09-14。対象は[LC4/LPLC2→DNp01の経路候補](Environment-Neural-Pathways.md)。Windows上で実MaleCNS全graphと現行 `MaleCNSShiuCompatibleLIF` を動かし、診断用localhost TCPからraw観測を受信する。通常Bridge／Unityへの入力追加やゲーム動作試験とは区別する。

## 実行前に固定する条件

- seed: 1701、1702、1703。
- 条件: SHAM（無刺激）、LC4のみ、LPLC2のみ、BOTH。3 seed × 4条件の12 trialを一つずつ実行する。
- 各trialは独立した初期状態から、無刺激500ms → 刺激500ms → 無刺激1,000ms。観測窓50ms、dt=0.1ms。
- 候補: 実注釈のexact type LC4全126細胞／LPLC2全185細胞。下流観測DNp01は10001（R）／10010（L）で、直接刺激しない。
- 入力は100Hz Bernoulli（各tick p=0.01）、外部電位加算68.75という既存controllerの診断条件。同一seedでは全311細胞の乱数列を共有し、条件ごとのmaskで採用する。自然視覚の角速度・角サイズから校正した刺激ではない。
- 入力候補と既存Action入力の和集合に、既存モデルの外部入力細胞と同じrefractory=0を設定する。この設定はSHAMを含む全条件で共通。他細胞は22 tick。候補の入力資格を加えた診断条件であり、本番と数値的に完全同一とは呼ばない。
- 重み・NT policy・decoderは変更しない。Actionを視覚刺激と偽って流用せず、固定motorも送らない。trial間の初期化と同一trial中の持続状態を区別する。
- 壁時計上限300秒。結果を見て刺激強度・観測時間・seedを変更する探索は行わない。

## 観測と判断

各窓のsequence、脳内時刻、入力イベント件数とhash、入力細胞の発火、DNp01左右の発火数／Hz／平均V／平均G、全graph発火数を記録する。刺激した細胞自身の発火を下流応答としない。

主要な比較は、各seed・入力条件の刺激500ms中のDNp01発火数と、同じseedのSHAM同区間との差とする。左右・seedをまとめて一部の不応答を隠さない。発火がなく電位／conductanceだけ変化した場合は、発火伝播確認とは区別して記録する。

刺激終了直後と終了後最後の500msを別に集計し、SHAMとの差から残留発火・電位を記録する。入力イベント0と神経活動0は同義ではなく、残留を「停止済み」で上書きしない。この診断での入力OFFは通常ゲームのSTOP／緊急停止／再接続試験の代わりではない。

成功の範囲は「明示した実験的刺激に対し、現行LIFで独立した下流細胞の応答を測れたこと」。危険の認識、感情、報酬・嫌悪、学習、実際の回避行動の実証にはしない。`ready=false` を維持する。

## 実行結果

**12 trial完了。3 seedすべてでLC4のみ・LPLC2のみ・両方の各条件からDNp01左右への発火応答を確認した。** 無刺激では0。以下は刺激500ms中の発火数で、R/Lは10001/10010を表す。

| seed | SHAM R/L | LC4 R/L | LPLC2 R/L | BOTH R/L |
|---|---:|---:|---:|---:|
| 1701 | 0/0 | 46/58 | 44/48 | 65/75 |
| 1702 | 0/0 | 48/58 | 44/48 | 66/74 |
| 1703 | 0/0 | 46/58 | 44/47 | 65/74 |

基準区間は全graphで発火0だった。全条件で刺激終了後の入力イベントは0。終了直後の50ms窓にはDNp01左右合計で最大2発火が残ったが、それ以降の観測窓ではDNp01の発火はなかった。最後の500msは全trialでDNp01と全graphの発火が0、DNp01の各窓平均Vと静止値−52との差の最大値は約8.38×10^-11だった。入力OFFと即時の神経無活動は区別する。

今回の結果は候補への実験的入力が下流へ伝播することを支持する。直接edgeだけの寄与を切り分けるablationは行っていないため、観測した発火を全てLC4/LPLC2→DNp01の直接edgeだけに帰属させない。また3 seedは計算上の乱数反復であり、異なる生物個体の反復ではない。入力群の同時刺激、入力候補のrefractory=0、静止状態からの試行という条件に限る。

## 実行・証拠

```powershell
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/visual_threat_brain_probe.py --execute
```

`2026-09-14T10:35:24Z`完了。Windows診断server `127.0.0.1:60159`、自己所有PID 51248。MALECNS_EXPERIMENTAL／LIVE／diagnosticOnly、ready=false。166,700細胞、19,670,694格納edgeの実graphを既存LIFで実行し、TCPから480 frame、sequence 1→480を受信した。各trialは脳内0→2,000ms、計24秒。固定値の応答やReplayによる代替は使っていない。

全体壁時計約70.69秒。窓50msの処理時間は中央値156ms／p95 219ms／最大234ms。frameごとのRSS観測最大418,537,472 bytes（約399.15MiB）。これはsampling最大であり、全期間の厳密なピーク保証ではない。TCPのsequence欠落・診断エラーなし、stderr 0 bytes、自己所有serverの終了を確認した。通常Bridgeのstale判定、Action受付からのE2E、Unity制御はこの診断の対象外で、未検証とする。

graph集約SHA-256=`dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569` は既存checkpointと一致。config SHA-256=`4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`。probe source SHA-256=`b6c555c16f1b721fbbcf92fdbddcdcb62633e4436126aed945f36ab5e2092fb2`、shiu_compatible SHA-256=`af90d268450945169d63692e13d0260b5e9ff478be9780dea425a777114afa49`、lif_kernels SHA-256=`d0bb9c3fc7ef40ccd01769a1119f19ac92046672d2976f30a9a21ce5e172b116`。4 graphファイルの個別hash・注釈/NTのhash・入力全IDはmanifestへ保存した。

依存: Python 3.10.12、NumPy 1.24.3、PyArrow 24.0.0、Numba 0.61.2、llvmlite 0.44.0、psutil 7.2.2。固定schedule・共通乱数と条件mask・同じ長さの区間だけでcountを比較する純粋3テストもPASS。これらの純粋テストと上記実LIF測定を分けて扱う。

原本は `artifacts/neural-feedback/visual-threat-brain-probe/events.ndjson`、`summary.json`、`server.stderr.log`。summaryのcompletedは480 frameの計測完了であり、ゲームまたはモデルのreadyを意味しない。

## 次のgate

通常通信への実装、Windows実Brainの移動併用・取消検証、Unity/API最終試験は、後続の [ゲーム統合記録](Visual-Threat-Game-Integration.md) を参照。Playerの神経入力・観測と操作は成功、DNp01実測値の実況は未確認。

危険の下流応答を測定できたため、次は環境の接近観測から刺激への変換、Brainへの期限付き適用・取消、DNp01 raw readoutの通常通信への追加を検討できる。ただし今回は通常Brain Serverの6 Action処理・Unity・motor・神経状態との共存を検証していない。既存移動中の応答や停止、世代変更、失効を確認してからゲーム側を有効にする。甘味入力・affectiveProxy・感情・学習は今回の実測から有効化しない。
