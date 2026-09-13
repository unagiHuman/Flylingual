# プレイヤー役の自動音声テスト案

2026-09-13時点の設計案を保存した文書。以後の実装・実行手順は [Native-Synthetic-Voice-Tests.md](Native-Synthetic-Voice-Tests.md) を参照。以下の「未実装」「未実施」は検討時点の記述である。

## 推奨する2つの経路

| 経路 | 目的 | 確認できる範囲 |
| --- | --- | --- |
| 合成音声ファイル→Unityの共通音声送信経路 | 通常の自動回帰試験。人の発話を待たず、同じ音声を再利用する | 音声変換・送信、Live認識・委譲、Responses解釈、実Brain適用、身体運動 |
| 合成音声をスピーカー再生→実マイク | 機器込みの追加試験。同じfixtureを使う | 上記に加えて出力機器・マイク選択・収録・音量・室内音響の影響 |

初版はファイル入力を実装し、機器経路は別モードとして追加する。ファイル入力を「実マイク合格」と表示しない。スピーカー試験も人間の自然発話や全機器構成を代表するものではない。仮想マイクドライバーの導入は初版の前提にしない。

このPCの`System.Speech`による読み取り専用列挙で、日本語のMicrosoft Haruka Desktop、Ayumi、Haruka、Ichiro、Sayakaを確認した。まず既存の日本語音声でWAVを生成し、音声名・速度・形式・台本・ファイルhashを固定する。WAV生成には[MicrosoftのSpeechSynthesizer](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.setoutputtowavefile)を使用する案。今回、生成・発声は未実施。毎試行で再合成せず、完成音声の聞き取り確認後に同じファイルを使う。音声生成はローカルで完結できるが、Live／Responsesを通す試験のAPI利用は通常どおり発生する。

## 既存コードへの組込み

現在の[ConversationSessionController](../../UnityProject/Assets/RuntimeIntegration/Conversation/Client/ConversationSessionController.cs)はマイクの`PcmChunk`を受け、`OnPcmChunk`で音声を送信している。`MicrophoneTransmitting`に依存するため、外部からこのメソッドを呼ぶだけでは試験にならない。

入力源を実マイク／fixtureから一つだけ選択し、PCM送信処理を共用する最小の分離を行う。fixtureを実マイク収録中と偽装せず、`inputSource=synthetic_fixture`、fixture送信状態と実マイク収録状態を分けて表示・記録する。通常起動の実マイク自動待受は維持し、fixtureモードは明示的な検証操作だけで有効にする。ミュート・緊急停止・会話世代変更・終了による入力停止と古い音声の破棄を共通で適用する。

WAVのヘッダーを解釈し、既存[PcmStreamConverter](../../UnityProject/Assets/RuntimeIntegration/Conversation/Audio/PcmStreamConverter.cs)を通して24kHz mono PCM16LEへ変換する。送信は実時間に合わせ、現在の100ms分割・Bridgeの送信周期補正を使用する。ファイル全量の一括送信はしない。これは[OpenAI公式のWebSocket音声入力](https://developers.openai.com/api/docs/guides/voice-websockets)にある、収録sample rateに合わせた連続した順序付き音声送信に沿う。

GPT Liveの返信は従来の返信再生へ流す。ファイル試験では物理マイクを併用せず、返信音声を入力音声へ混ぜない。スピーカー試験ではfixtureの直接送信を無効にし、実マイク経由だけにする。二重入力を避け、音量・機器名・再生／収録開始時刻も記録する。

Unityの既存制御WSを使用する。外部runnerが2本目の制御WSを開かない。Brainは実Windows LIVEのままで、fixtureは音声入力だけに限定する。モデル、TTL上限、神経値、刺激、decoder、motor、ready=falseを試験のために変更しない。正解Actionや台本の文字列をLive／Responsesへ別途渡して認識を助けない。

## 最初に作るシナリオ

| 試験 | 自動で音声を入れるタイミング | 合否の要点 |
| --- | --- | --- |
| 音声から前進・左右旋回 | 起動後のLive・fresh STOP・身体準備完了後 | fixture由来のvoice分類→Brain applied→実motor・CPG・移動／旋回を確認 |
| 「止まって」で停止 | 「8秒間前に進んで」の実Brain適用と身体始動を観測した直後 | 新しいvoice STOPの適用と身体静止。先に期限切れ／safety STOPが来た場合は音声停止合格にしない |
| 期限切れ後の再指示 | 前進の期限切れSTOP適用と静止を確認した後 | 次の別方向音声を受け付ける。epoch・会話世代・Brain sessionを維持。3巡し、再有効化や旧指示再送を行わない |
| GPT返信中の指示 | 実際に非ゼロ返信音声が再生されているとき | 重なった音声入力の委譲・Brain適用・身体反応まで確認。返信自体の中断は別判定 |
| 継続待受 | 操作と無音を交え、規定時間繰り返す | 入力欠落、queue超過、増え続ける送信遅れ、stale、操作受付停止を検出。15分試験は短い試験合格後の別gate |

音声STOP試験は単に「何秒後に再生」と決めず、実際の身体始動を開始条件にする。停止の分類・適用が期限内に間に合わなかった場合も原本を残す。合格させるためにTTLを延長したり、テキストSTOPを混ぜたりしない。既存の静止判定（実Brain motorの絶対値0.01未満を0.5秒、身体水平速度0.05m/s未満・CurrentMotor各軸0.03未満など）を条件と区間定義付きで再利用する。

初版の操作系列は一つの音声指示ごとに結果を確定して次へ進む。唯一、動作中STOPや返信中指示では指定した重なりを作る。clarify・返信未開始・旧世代・期限不足・対応不明は個別に記録し、成功するまで無制限に再試行しない。操作配線の試験では既存probeと同様にケース間だけ物理姿勢を復元できるが、連続待受／割込のケース途中では復元せず、Brain状態もリセットしない。

## 判定・証拠と実装範囲

[NativeConversationProbe](../../UnityProject/Assets/RuntimeIntegration/Conversation/NativeConversationProbe.cs)の既存試験は`SendPlayerText`を使用するため、そのまま音声試験とは扱えない。[NativeVoiceObservationProbe](../../UnityProject/Assets/RuntimeIntegration/Conversation/NativeVoiceObservationProbe.cs)の実frame・source・身体姿勢観測を再利用し、音声fixture専用の状態遷移を追加する。[verify_native_player.py](../../tools/verify_native_player.py)にも独立した音声fixtureモードを追加する案とする。これらの新規モードは未実装。

追加するのは、ローカル音声生成ツール、台本と期待値のmanifest、Unityのfixture入力・シナリオprobe、既存runnerの選択肢、結果集計。manifestに正解Actionを持たせるが、検証器だけが読み、会話モデルの入力やプロンプトへ渡さない。

記録はfixture ID/hash、入力源、PCM sample範囲と送出開始・終端、epoch／conversation generation、Live入力時刻とdelegation、voice commandId、Brain requestId／sequence、fresh実frame、身体変化をつなぐ。現在の受動probeに不足するepoch・generation・返信再生状態も追加する。音声時刻で対応が特定できない委譲は未確認とする。合成台本以外の会話本文・実マイク音声の常時保存は追加しない。

音声開始→身体始動／静止のE2EはUnity内の同じ単調時計で測る。Bridge内の分類・適用時間と分け、異なるプロセスの時計をそのまま引かない。観測間隔に応じた測定精度も記す。終了時は所有process残存と、プロトコル終了イベントの確認を分けて記録する。

実装後の順序は、音声ファイル形式・周期・停止／世代破棄のオフライン検証、実Live／Responses／Windows Brain／Unityでの前進→音声STOP→次指示、返信中入力、6動作各3回と待受3巡、長時間試験、機器経路の順。各結果を「合成音声入力」「物理マイク入力」と明記し、自然発話の認識品質や機器の信頼性を混同しない。
