# Windows Live Brain：処理順統一＋Tibia接触診断（2026-09-12）

## 結論

Windows実Brainに接続して、通常接触・LM/RF/RM Tibia接触除外を各3回、計12回測定した（別に通常接触の接続確認1回）。Tibia接触を変えると初期姿勢と旋回量が変化したが、以前の固定Replayでの約54度の右旋回はこのLive通常条件では再現しなかった。初動の小さな右振れは残る。逆旋回原因の確定・修正完了とは扱わず、本番へcollider変更を適用しない。

## 実際の接続と入力

- Windows上のBrain/MaleCNS/brain_server_analog.pyを127.0.0.1:18766で起動。
- 各試行は新しい所有server process（seed20270101）とUnity Player一つ。Mac・mock接続・Replay駆動は使用しない。
- Unity clientからSTOPを送り、対応する実BrainFrameの受信とzero近傍を確認してから、保存した物理初期状態へresetし、FORWARD_Lを送信。
- MotorSourceは既存BrainMotorSource。受信forward/turn→既存平滑化→CPG→関節drive。Action名によるmotor補正なし。
- Brainを待つ間だけUnity物理をpauseし、試験開始後はtimeScale=1、fixedDeltaTime=0.02。初期CPG位相90°。
- 既存WindowsReplayDemoのAwakeはfixtureを読み込むが、診断の最初の物理tick前にLive MotorSourceへ切り替える。固定Replayによる物理試験はしていない。

## 接触条件

全条件で既存の診断用処理順統一を有効にし、CPG targetを全脚へ適用してから吸着を一回評価する。

LM/RF/RMの各条件は、その脚のTibia colliderと環境colliderの31組だけPhysics.IgnoreCollisionを設定。FootPadの衝突は維持。colliderを削除・無効化せず、質量・joint limit・摩擦・adhesion strengthは変更しない。実ログでも対象Tibiaの接触件数0を確認。ignored-collision-pairs.txtに全組を記録。

通常接触と各除外条件で物理初期状態は共通。状態は現Flylingual内のcontact-timing-control/reset.jsonlから抽出し、旧Flytestは参照していない。条件の実行順は各反復でNONE→LM→RF→RM。

## 結果

正は右、負は左。各条件n=3。

|条件|送信開始から8秒のyaw平均|同yaw範囲|最初のFORWARD_L Frame受信から2秒間のyaw平均|
|---|---:|---:|---:|
|通常接触|-13.86°|-16.87～-11.28°|+2.65°|
|LM Tibia除外|-4.53°|-9.51～+4.75°|+5.30°|
|RF Tibia除外|-21.66°|-27.79～-12.16°|+3.85°|
|RM Tibia除外|-25.02°|-30.79～-15.03°|-0.26°|

最初のFORWARD_L Frameが物理ログへ現れるまで1.10～1.58秒。したがって8秒の列は「8秒間同じmotorを印加した結果」ではない。Frame受信後の2秒列は、body.csvを受信時刻で切り出してyaw差分を積算した。

LM除外は3回中1回、8秒で右へ4.75度。接触を消すだけで安定して改善するとは言えない。RF/RM除外は8秒で左旋回量が大きい傾向だが、各試行の実神経出力は完全一致していない。FORWARD_L期間の平均forwardは約0.588～0.637、平均turnは約−0.418～−0.277。出力差と接触差の因果を厳密には分離できていない。

最初の0.5秒のyawは通常約−0.16度、LM除外約+2.29度、RM除外約−1.42度。これはFORWARD_L Frame受信前であり、接触変更そのものがSTOP中の初期姿勢の落ち着き方にも影響することを示す。これをBrainによる操舵効果に数えない。

## 検証と制約

- Windowsビルド成功、全12 Player終了コード0。各試行後STOPを送り4秒待って正常disconnectし、所有serverを終了。STOPの物理的停止完了は今回の判定対象外。
- 本比較の受信BrainFrameは252件（開始STOPと終了STOP待機を含む）。全試行でsequenceが単調増加。
- backend=MALECNS_EXPERIMENTAL、ready=falseを受信値のまま維持。
- client/protocol error記録0、Player.logのException:/error CS検索該当なし。
- 4,800物理サンプル中、観測age>0.75秒は64件、最大0.909秒。既存stale時のsafe STOPは変更していない。通信の揺れは比較の制約。
- 別の接続確認1回はstale43/400。これは本比較へ混ぜていない。
- 28,800脚サンプルで適用前/物理後の時刻・脚ID対応を確認。stance不一致0。除外対象Tibia接触0。
- fall（既存y<−3判定）は0/12。ただしこれだけで支持・登攀の成功とは扱わない。
- 今回は問題の位相90°に絞った検証。位相0°、右前進、コース踏破は未実施。接線impulseの欠測から、yaw力積収支の閉合も未達。

## 保存と再実行

artifacts/windows-malecns/live-tibia/ に12試行。各フォルダにmanifest.json、live-wire.jsonl、live.csv、body.csv、legs.csv、support.csv、contacts.csv、ignored-collision-pairs.txt、Player.log、brain-server.log、process-result.jsonを保存。

集計はlive-tibia-summary.json。brain-source-hashes.json、各manifestのAssembly-CSharp.dll/初期状態/診断コードhashを参照。別の接続確認はartifacts/windows-malecns/live-tibia-baseline/NONE-0。

実行：専用venvのpythonでtools/run_live_tibia_diagnostic.py --output <新しい出力先>。既存試行ディレクトリには上書きしない。集計：tools/analyze_live_tibia.py <出力先>。

## 変更ファイルと次の判断

- UnityProject/Assets/VisualDemo/FixedPhysicsDiagnostic.cs：Windows Live入口、STOP受信gate、接触除外、Liveログ。
- tools/run_live_tibia_diagnostic.py：所有Windows server＋Playerの逐次実行。
- tools/analyze_live_tibia.py：接続、入力、処理順、除外接触、旋回の集計。
- 本レポート。

SerializeField変更なし。Brain/decoder変更なし。診断flagがない通常ゲームには接触除外を適用しない。未commit・未push。

次はcollider除去を本番へ入れるのではなく、Windows Liveの初動を基準にする。必要なら通常接触でFrame受信後の時間軸とstaleの影響を先に揃え、再現する右振れだけを対象に最小修正を評価する。今回の結果から「Tibiaが逆旋回の唯一の原因」とは結論しない。
