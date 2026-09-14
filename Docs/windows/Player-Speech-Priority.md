# プレイヤー発話の優先

2026-09-14。台本・チュートリアル・実況の途中でも、プレイヤーの発話開始時に再生を中断し、最新の発話を優先する。日英、control／chat_onlyの両モードに適用する。操作の委任・安全規則は変更しない。正本は [Brain・GPT Live共通設計](../Brain-GPTLive-CrossPlatform-Design.md)。

## 実装

既存の100ms PCMチャンクとRMS閾値0.012を使って音声活動を検出する。600msの無音境界を越えたonsetでBridgeへ通知し、ネット送信awaitより前に `discard_audio` を発行する。台本の残り音声をローカル再生キューに保持して後から再生することはしない。これは発話内容の認識でもAction入力でもない。

発話開始から6秒間は会話を優先する。発話終了から1秒以内、intent処理待ち、または優先期間開始後の非無音出力から1.5秒以内も優先を維持する。無音出力で期限を延ばさない。優先中の台本・実測cueはcommentaryではなくthinkingへ渡す。

最後の入力音声活動から150ms未満の生成audioは破棄し、後で再生するためにqueueへ戻さない。150msを過ぎた新しいaudioは通す。ASRは1.5秒のburst境界で一度だけinstructions redirectを送り、断片ごとに回答を消去しない。envelope onsetと最初のASRは別経路であり、同じ発話で通知が複数回になる可能性はある。conversation非accepting時は発話割り込み・ASR redirectの副作用を起こさない。

日英promptは、台本を最後まで読まず中断し、最新の質問・指示へ応答し、中断した台本を自動再開しないことを指定する。危険実況もプレイヤー発話を優先する。これは実行側の安全監視やSTOPを解除するものではない。

利用するLive WebSocket仕様の参照先： [公式Voice WebSocketsガイド](https://developers.openai.com/api/docs/guides/voice-websockets)。既存のsession input／instructions／thinking／commentary append経路を使い、未定義のresponse.cancel等を追加しない。ローカル再生抑止と、API側の発話内容・再開抑止の実証は別に評価する。

## 検証

純粋契約テスト73件PASS、Unity compile PASS（親確認）。テストは発話検出、ネット送信待ちより前の破棄、ASR burst、非accepting抑止、cueのthinking化と期限後復帰、150ms後のaudio通過、無音での期限延長防止、日英prompt、既存質問チャネル互換を対象とする。実Brainの動作を代替する証拠ではない。

初回実測の原本：`artifacts/voice-script-interrupt/runner-metadata.json`、`report.json`。実Windows Player／Brain／Live APIへ合成音声fixtureを送信したscript_interrupt試験で、物理マイク試験ではない。

| 項目 | 初回 |
|---|---|
| 総合判定 | incomplete |
| error | script_interrupt_stop_not_maintained |
| 台本音声との重なり | overlapVerified=true、replyOverlap=true |
| STOP適用／身体静止 | applied=true／settled=true |
| first PCM→discard | 201.59ms |
| 音声終了→STOP適用 | 700.46ms |

初回の停止維持gateが更新されないHUDLastAppliedActionを参照したため、総合判定はincompleteとなった。STOPの適用・静止は観測されたが、原本のfailed gateをPASSへ書き換えない。生成ソース・fixture・ビルドのhash、依存version、RSSはrunner-metadata原本に保持する。上記遅延はこの1試行の値で、最大遅延保証ではない。

### 2回目

`artifacts/voice-script-interrupt-v2`：修正gateでPASS。通常Windows Playerを22:40:13→22:40:24 JSTに再ビルドし、Windows Brain 127.0.0.1:18766、MALECNS_EXPERIMENTAL／LIVE、実GPT Liveで実行。受信したready=falseは維持した。

```powershell
.\.venv-bridge\Scripts\python.exe tools/verify_native_voice.py --fixtures artifacts/voice-fixtures/haruka-persistent-v1/manifest.json --suite script_interrupt --output artifacts/voice-script-interrupt-v2 --capture-test-transcript
```

- 台本cue受理後の新規nonzero再生と最初のPCM投入時の重なりを確認。first PCM→discard 214.31ms、音声終了→STOP適用804.50ms。
- requestId=3／適用sequence=476、fixture_audio_overlapによる音声相関、STOP適用・身体静止、2秒の停止維持を確認。sameEpoch／sameSession／freshMaintained=true、23回の新規frame進行、最大frame age 123.41ms。
- error空、Player例外0、exit 0、所有process残存なし、終了後port解放。wall 63.843秒、process tree sampled peak RSS 1,164,795,904 bytes。
- 実施は日本語合成STOPの1ケース。認識文字は「とどまって」でfixtureとの文字列一致はfalseだが、意味解釈と相関STOP適用は確認。初回を含む2試行を汎用的な最大遅延の保証とは扱わない。

ソース・設定・graph・fixture・exe／dllのSHA256と依存版は同ディレクトリのrunner-metadata.json、現行ソース照合はcurrent-source-hashes.json。Python 3.10.12、aiohttp 3.14.3、NumPy 1.24.3、Numba 0.61.2。生成exeはGit管理外の `artifacts/windows-native-conversation/unity/FlylingualConversation.exe` を更新した。CLIの5秒応答timeoutとは別にBuildReportのSucceededを確認した。

## 未検証

物理マイク・スピーカーecho、一般質問の割り込み、英語音声、台本を再開しないことの実際の発話内容は未検証。合成PCMの受信・STOP成功と、人間が話したときの会話体験を同一視しない。
