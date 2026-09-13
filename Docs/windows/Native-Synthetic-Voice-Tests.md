# 合成音声によるWindows Player検証

2026-09-13。`generate_voice_fixtures.ps1`でプレイヤー役の日本語音声を生成し、`verify_native_voice.py`で正式Playerへ入力する。通常起動の実マイク待受と区別し、テスト時だけ `-flyVoiceFixtures` で入力源を選択する。

## 実行

リポジトリルートから実行する。Windowsの日本語音声合成が利用可能なユーザーセッションを使う。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/generate_voice_fixtures.ps1 -OutputDir artifacts/voice-fixtures/haruka-ja-v1
.venv-bridge/Scripts/python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-ja-v1/manifest.json --suite smoke --output artifacts/voice-tests/smoke-01
```

出力ディレクトリは毎回新しくする。fixtureは台本・音声名・速度・SHAが一致する場合だけ再利用する。1音声30秒以内のPCM16 WAVを24kHz monoに変換し、100msずつ送る。送信予定時刻を維持しつつ、遅れの回復も最低90ms間隔・1フレーム1chunkに制限する。ファイル入力中は実マイクを開かない。台本や期待Action/Planは検証器だけが読み、GPTへテキストとして渡さない。

| suite | 内容 | 既定の上限 |
| --- | --- | --- |
| duration | 時間指定なしの前進/右旋回/左旋回。音声→実Brain適用→身体→満額の動作時間→TTL停止を順に検証 | 180秒 |
| persistent | 60秒継続と10秒ごとの身体移動、「そのまま」の無再送、音声STOP、継続から有限動作への置換、条件追加の期限保持、旧操作の不復活 | 180秒 |
| smoke | 前進→音声STOP、返信中の旋回、期限切れ後の別指示3巡、曖昧な量の指示 | 240秒 |
| full | smokeに加えSTOP/前進/左右旋回/左右前進を各3回 | 900秒 |
| plans | 「ちょっと右」「右側に進んで」「違和感があったら止まれ」のPlan分類と実行境界 | 240秒 |
| soak | smoke後に指示と無音を繰り返す | 300秒 |

`--seconds`で1〜3600秒を指定できる。途中の失敗や期限不足を成功へ繰り上げない。6動作の独立確認時だけ既存の初期身体姿勢を復元する。Brain・motor・神経値は書き換えない。

`duration`用の3音声を含む最新版fixtureは、新しいディレクトリ（例 `artifacts/voice-fixtures/haruka-ja-v2`）へ生成する。受付時の`executionDurationMs`と同じBridge時計での期限切れを照合し、解釈時間を差し引いていないことを確認する。`intentAgeMs`は別に記録する。

## 何を合格とするか

実GPT Live→Responses→Windows Brain→実BrainFrame→CPG/PhysXを使用する。既存の制御WSを共有し、runnerは追加のBrain clientや制御WSを作らない。音声fixtureの実送信sample時刻とLive delegationの入力時刻の重なりを確認し、commandId/requestId/sequenceをたどって身体変化を観測する。異なるプロセスの単調時計を直接引き算しない。

音声STOPは、直前の動作の期限切れやsafety STOPより先に、fixture由来のSTOPが適用された場合だけ合格にする。静止は実motor、CurrentMotor、接地、水平速度の連続観測で判定する。実マイク機器・室内音響の検証は含まない。未委任 transcript 補完の実マイク受入れも未実施である。

曖昧な指示には既存の行動計画を使用する。UnityからBridgeへの `local_safety_observation` はソース上で接続済みだが、検証Playerで新鮮な観測が届くことを個別に確認する。観測欠損で実行を拒否されたplanは `blocked` と記録し、Plan名の誤分類や音声との対応不明とは区別する。安全な観測値を捏造してPlanを動かさない。Planの複数step・危険停止の身体合格判定は追加gateであり、分類成功だけで身体操作合格にしない。

継続指示の仕様は[指示の継続と更新](../integration/Persistent-Intents.md)を参照する。
`persistent`用fixtureは新規ディレクトリへ生成する（例 `artifacts/voice-fixtures/haruka-persistent-v1`）。
`--suite persistent`は最初の移動だけで合格せず、60秒以上の同一executionと10秒ごとの水平移動を要求する。
地形の端や障害物で身体が止まる場合も、継続歩行成功にしない。受入れでは、動けなくなる、停止できない、次の操作を受け付けないといった主要プレイ経路を優先し、条件更新などの厳密 gate の未達は残課題として分けて記録する。
「そのまま」と条件追加は通常はfixture音声→delegation→commandId→`execution_updated`の相関を確認し、Brainへの再送がないことを検証する。Live 未委任 transcript 補完を使う場合は、candidate→同じ Responses schema→既存実行経路の相関を別に保存し、実 delegation と混同しない。classification-02 の実 Responses 検証は 29 件中 28 件一致であり、nudge の無期限化を提案した 1 件は実行側が拒否しても分類合格にしない。

## 出力

- `report.json`: シナリオ別の分類・対応関係・適用・身体運動・停止・不成立理由。
- `events.jsonl`: fixture送信と、本文/PCMを除いた許可済み診断イベント。
- `observations.jsonl`: 入力源、実Brainのbackend/ready、sequence、鮮度、身体位置/速度/旋回、返信再生。
- `runner-metadata.json`: 全体結果、process終了、残存PID、port解放、RSS、source/config/data/artifact/fixture hash。
- `player.log`, `player-stdout.log`, `runner-events.jsonl`: 実行時の原本。

LIVE MALECNS_EXPERIMENTALの`ready`は受信値をそのまま記録する。プロトコル終了の観測と、runnerによるprocess回収は別の証拠として扱う。runnerのhashは起動前に固定し、使用するPython・aiohttp・numpy・numba・llvmliteの版も残す。

Live delegation の通常経路は [React to transcript fragments](https://developers.openai.com/api/docs/guides/live-delegation) に従う。

## 診断プロトコル

既存control WSで `{"type":"voice_test_observation","enabled":true}` を送ると、その接続に限り `voice_test_diagnostic` を受信する。切断時に無効化する。通常audioの仕様は維持する。

試験audioには任意の `fixtureId`（ASCII英数字/_/-、1〜64文字）と `fixtureChunkIndex`（0〜100000）を両方付ける。Bridgeがこのタグを取り除き、Liveには従来のPCMだけを送る。送信後の `audio_fixture_sent` は、そのLiveセッション全体の無音を含めた `audioStartMs/audioEndMs` を返す。`delegation_observed` の `startMs/endMs/offsetMs` と対応を確認する。旧epoch/会話世代・不正タグは拒否し、世代変更で未送信queueを破棄する。

`input_transcript_observed` は認識断片の時刻だけ、`context_append_observed` はLiveの通知受領だけを示す。委任や実行の成功とは区別する。既定ではProbeは現在fixtureの認識文を一時メモリで比較し、`recognizedCharacterCount` と `recognizedMatchesFixture` だけを保存する。比較はUnicode正規化と空白・句読点除去後の完全一致であり、不一致でも意味の等しい認識はあり得る。この診断をAction生成や合否判定には使わず、字幕本文も保存しない。`--capture-test-transcript` は fixture input が有効で物理マイクが無効の時だけ `report.json` の case `diagnosticTranscript` を保存する診断 opt-in であり、PCM を保存せず、マイクを有効化しない。
