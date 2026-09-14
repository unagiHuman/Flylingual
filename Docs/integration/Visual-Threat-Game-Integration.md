# 危険イベントの実Brain接続（2026-09-14）

実装済み。通常Windows Brain Serverで危険入力とFORWARDの併用、解除、STOP、切断後の取消を確認した。Unityはコンパイル・Playerビルドまで成功。実GPT Liveを伴うPlayer試験は外部送信の自動承認レビューで拒否され、未実施。ゲーム上の警告から実況までの完了判定は保留する。

## 実装境界

既存 `threat_started` 一回を、実注釈LC4 126細胞＋LPLC2 185細胞への固定100Hz Bernoulli入力へ変換する。新しい操作や収集目的は追加しない。実際の視野・角速度から校正した刺激ではなく、`event_proxy_v1` と明記する。設定定義 `Brain/MaleCNS/config/visual_threat_v1.json` を追加し、注釈hashと入力集合hashを検証する。DNp01 10001（R）／10010（L）は刺激せず発火数を読む。

最大500ms脳内時間、または受信から750ms壁時計。環境イベントの経過時間と送信待ちを差し引く。実Brainは実時間より遅いため、500ms分の刺激完走を保証しない。実行中の50ms脳内窓は中断せず、期限と取消は次の窓境界で反映する。入力OFFと発火ゼロは区別する。

STOPはmotorのlatest slotと同じlockでsensoryを取消し、後続FORWARDがSTOPを上書きしても古い刺激は復活しない。警告終了・取消・落下・叩かれ、切断、世代変更でも解除する。刺激中だけ入力候補のrefractoryを0にし、窓の後に元値へ戻す。独立した感覚用RNGを使い、無刺激時のAction乱数列・重み・decoderを保持する。

通常BrainFrameの `raw.visualThreat` から固定ID・型・発火率整合を検証し、Bridgeが `visual_threat_observation` を送る。実測窓と環境の事実を分け、既存 `environment_observation.neuralInputApplied=false` は維持する。GPTには日英の短い観測文脈をON/OFF変化時に渡す（最低1.5秒間隔、発話・操作待ち中は抑止）。人格は維持し、恐怖・嫌悪・回避成功を測定事実として断定しない。甘味入力、affective readout、学習は未実装。`ready=false`。

通信形式は [bridge-v1](../../Contracts/bridge-v1/protocol.md) の visual threat extension を参照。

## 実測

```powershell
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/visual_threat_inactive_trial.py
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/visual_threat_server_trial.py --execute
& artifacts/windows-malecns/.venv/Scripts/python.exe tools/visual_threat_server_trial.py --execute --output artifacts/neural-feedback/visual-threat-server-coexist
```

- 無刺激比較: seed 20270101、50ms窓、6 Action＋末尾STOP、各3窓。拡張なし／設定あり無刺激の実全graphを独立初期化し各21 frameを比較。performanceと追加raw以外の全JSON値が完全一致。両hash `8203f3ebf295ca3ba34d251d1bf92fd0a8da80cf3eac1781f619e61cb652fc32`。この比較はTCP／Unity試験ではない。
- production server初回: `127.0.0.1:63958`、10 checks成功。ONのDNp01 R/L=6/7発火、期限切れ、STOP、STOP後新Action、再接続の無刺激を確認。自己所有serverは終了。
- 移動併用: `127.0.0.1:55228`、14 checks成功。26受信frame、sequence 0→26（切断中1窓の欠測）、protocol errorなし。FORWARD中sequence 18で入力イベント1,562件、DNp01 R/L=6/7発火（120/140Hz）、神経由来motor.forward=0.6135。明示OFF後もFORWARDを保持し、STOPを受付。再接続後入力0。STOP適用直後のmotor減衰は残り得るため、身体の瞬時停止とは呼ばない。
- 感覚送信→最初の入力適用frame受信は4 pulseで265/406/438/422ms。これはUnity/APIを含むE2Eではない。50ms窓の壁時計処理時間は26窓の中央値209.6ms、p95 221.6ms、最大226.8ms。全試験壁時計6.61秒。LIVE／MALECNS_EXPERIMENTAL、ready=false。
- RSSの初回集計6,115,328 bytesはvenv launcherのみの可能性があり、Brainのメモリ使用量として採用しない。runnerは子孫プロセス別・合計のsample最大を記録するよう修正したが、この計測修正後の再実行はしていない。

全CNS 166,700細胞／19,670,694格納edge。graph hash `dd49c763a2eb2e03a0d1f450a7743bf9f3a13922e2dab02b0f348f44aaf4a569`、motor config `4a2a785741f58ba07022618dcb91b8f99b5e5d2a1cc515017015b60119dfad96`、実行時Brain source `dd4e2fa781a0fd00576fa40ad8aa7bf1c36f943a0e0c4a656fe063050a376418`、visual config `fbc3176a51deaf97af6b0612ea803d28dfbb7c96694d165f7b9f8222332a57ba`。Python 3.10.12、NumPy 1.24.3、Numba 0.61.2、llvmlite 0.44.0、psutil 7.2.2。入力集合・NTの来歴は設定と前段の [診断](Visual-Threat-Brain-Validation.md) に保存。

原本: `artifacts/neural-feedback/visual-threat-inactive.json`、`visual-threat-server-trial/`、`visual-threat-server-coexist/` のsummaryとmessages.ndjson。測定後のRSS計測コード変更によりrunner現行hashは原本の実行時hashと異なる。server終了コード1はrunnerによる自己所有processの終了操作で、summary.completedとは別に記録している。

## 検証と残るgate

親実行の関連純粋テストはBridge 47件、Brain 11件PASS。Unity 6000.5.9f1のrecompileはerrors=[]、compilationFailed=false。safe-compileスクリプトは旧uloop設定が未導入で起動できなかったため、編集モード確認後に現行Unity CLIで実施。Dev-Localビルドは10:56:14→10:56:36 UTC、Succeeded。記録された1 errorはCLI応答の5秒タイムアウトで、BuildReport本文で確認した。

次のコマンドは未実行:

```powershell
& tools/neural_player_trial.ps1 -Name visual-threat-ja -Language ja -Question 0 -VisualThreat
```

試験はマイクなし、固定文「止まって」「前に進んで」「今どういう状態？」とゲーム／神経観測をOpenAI Live（`wss://api.openai.com/v1/live/sessions`）およびResponses（`https://api.openai.com/v1/responses`）へ送る。ローカル自由記述personaTextは試験中だけ空にし、元設定はfinallyで復元する。自動承認レビューは具体的な外部送信へのユーザー承認を要求した。承認後、既存ルートの実接触・警告開始・解除・DNp01入力ON/OFF・次の移動と停止を同じPlayerで検証する。英語の実発話、目視、ゴール到達、被弾・落下後の再プレイは別途未検証。
