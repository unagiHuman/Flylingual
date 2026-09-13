# 継続意図の検証記録（2026-09-13）

## 判定

厳密 suite は、条件更新と classification-02 の nudge 1 件に未合格を残す。一方、通常 Player の `persistent-normal-handoff-01` は、保持・「そのまま」・voice STOP・有限期限 STOP・旧操作非復活を確認した。動けなくなる、停止できない、次の操作を受け付けないといった主要プレイ経路の障害はこの実測で確認されていない。条件追加の未確認と分類の不一致は軽微な残課題として扱い、厳密 suite の未合格をリリース停止の根拠にはしない。人間マイクは未検証である。

## 確定済みの結果

| 範囲 | 母数・結果 | 判定 |
|---|---:|---|
| オフライン回帰 | 153 unit tests PASS、20.087 s。core、`live_session_clock`、transcript semantic 補完を含む | PASS |
| 実 Responses 分類 | classification-01 は実 Responses API 24/24 PASS。classification-02 は 29 件中 28 件一致、再試行 0。追加 transcript 5 件は PASS | 未合格 |
| 通常ステージ `persistent-01` | 継続 FORWARD は適用・移動したが、約 40 秒の観測中に進行窓が停滞 | 未合格 |
| 平面 `persistent-flat-01`／`02` | 継続 FORWARD は 60 秒超で移動。続く「そのまま」は delegation 未成立 | 未合格 |
| 平面 `persistent-flat-03`／`04` | 最初の FORWARD fixture が delegation 未成立 | 未合格 |
| 平面 `persistent-flat-05` | 最初の FORWARD は ASR 原文照合 true だが delegation 未成立 | 未合格 |
| 平面 `persistent-flat-06` | FORWARD 60 秒継続と「そのまま」の同一 execution 更新は PASS。STOP は原文照合 false、delegation 未成立 | 未合格 |
| 平面 `persistent-flat-07` | 保持・そのまま・voice STOP 静止・新継続→有限 8 秒置換は成立。条件更新は delegation 未成立 | 未合格 |
| 平面 `persistent-flat-08` | 保持・そのまま・STOP は PASS。STOP 後の新 persistent FORWARD は delegation 未成立 | 未合格 |
| 平面 `persistent-flat-09` | 保持・そのままは PASS。STOP は delegation 未成立 | 未合格 |
| handoff `persistent-handoff-02` | 6 cases PASS。c5 の有限 FORWARD は transcript semantic 補完、他は client delegation | PASS |
| 通常 Player `persistent-normal-handoff-01` | c1–5 PASS。保持・そのまま・voice STOP・有限期限 STOP・no-revival は true。c6 条件更新だけ `execution_update_not_confirmed` | 主要経路 PASS／厳密未合格 |
| full `persistent-flat-10` | 60.009 秒継続、continue、STOP、有限期限 STOP、no-revival は PASS。条件更新は期限後 `stale_execution` 拒否 | 未合格 |
| short-02 | 同一 source で条件追加と期限保持は PASS | PASS（限定） |

分類 artifact は実 Responses を用いた合成分類のみであり、音声、Brain、Unity 物理の代替ではない。classification-02 は 29 件すべてが `maxIntentAgeMs=8000` 以内だったが、`persistent_nudge_disallowed` だけが期待した `clarify` ではなく無期限化する `update` を提案し、28/29 で未合格となった。実行側は nudge の無期限化を `cannot_extend_nudge` として拒否するため、無期限 nudge は成立しない。ただし実行側の拒否を分類の合格には読み替えない。[classification-01 report](../../artifacts/persistent-intents/classification-01/report.json) と [classification-02 report](../../artifacts/persistent-intents/classification-02/report.json) を参照する。

通常ステージの停滞は `persistent_motion_window_stalled` として記録されている。継続実行自体は適用され、45.24 秒のケース中に水平変位 30.04 Unity units、forward travel 30.24 Unity units を記録したが、地形を原因と断定していない。[persistent-01 report](../../artifacts/voice-tests/persistent-01/report.json)

平面では、継続 FORWARD が `until_next_command` として適用された。flat-01 は 66.43 秒で horizontal displacement 71.25、flat-02 は 67.28 秒で 71.35 Unity units だった。flat-03〜05 は最初の FORWARD の PCM が Bridge 送信まで到達したが delegation がなく、適用 timeout で終了した。flat-05 は保存しない原文字幕との照合 bool が true だったため、ASR 文字列の完全不一致だけでは説明できない。

flat-06 は最初の FORWARD を 65.61 秒維持して同一 execution ID のまま `persistent_continue` を更新できた。FORWARD と「そのまま」は原文照合 bool true である。続く STOP は 16 PCM chunks が Bridge 送信まで到達したが、照合 bool false（認識長 5 chars）、delegation ID なし、`voice_apply_timeout` で未適用となった。字幕原文はどの run も保存していない。[flat-06 report](../../artifacts/voice-tests/persistent-flat-06/report.json)

flat-07 では、最初の継続 FORWARD は 67.20 秒の case 観測で適用され、その後の「そのまま」は同じ execution ID を保つ update として PASS した。voice STOP は delegation・適用・静止を確認した。新たな継続 FORWARD の後、有限 8 秒 FORWARD は delegation と適用までは記録され、raw events には期限 STOP がある。ただし probe は条件更新の delegation 不成立で終了 gate 前に停止したため、この期限 STOP と旧操作の非復活は PASS 扱いにしていない。条件更新 fixture 自体は delegation なしで `execution_update_not_confirmed` となった。[flat-07 report](../../artifacts/voice-tests/persistent-flat-07/report.json)

flat-08 は保持・「そのまま」・STOP を PASS したが、STOP 後に送った新しい継続 FORWARD は delegation がなく `voice_apply_timeout` で未適用だった。flat-09 は保持・「そのまま」を PASS したが、STOP の delegation がなく未適用だった。両 run とも cleanup 後の `remainingOwnedPids` は空で、`portsFreeAfterCleanup` は true である。[flat-08 report](../../artifacts/voice-tests/persistent-flat-08/report.json) [flat-09 report](../../artifacts/voice-tests/persistent-flat-09/report.json)

Bridge は、元の delegation ID に Brain application 完了通知を対応付ける修正を追加した。この修正は受理や身体移動の代替ではなく、Live 側の完了通知の配線を明確にするものとして扱う。

通常 Player `persistent-normal-handoff-01` は c1–5 を通過した。voice STOP と有限 `forward8` は transcript semantic 補完で適用され、保持・continue・STOP・finiteExpiry・noRevival はすべて true だった。c6 の条件更新だけは `execution_update_not_confirmed` で未合格である。runner wall は 70.016 s、player exception は 0、cleanup 後の owned PID は空、port は解放済みである。主要プレイ経路を確認した証拠であり、条件更新の厳密 gate を通過した証拠ではない。

slow-01 は rate -2 fixture manifest を用いた比較である。continue と STOP の双方で Live delegation は届いたが、その後の Responses が `clarify` を返した。handoff-01 の STOP は delegation event 自体がなく、別の未委任 transcript 問題である。cursor 修正の根拠は slow-01 continue の末尾だけで、delegation offset 67,400 ms に対する受信済み最終 fragment 67,400〜67,600 ms が旧 `end <= offset` 条件で選択されなかった点である。修正後は `start >= cursor` かつ `start <= offset` を選択し、選択済み fragment を除去、cursor を `max(offset, selected ends)` へ進め、`clear_context` は cursor を巻き戻さない。境界 9 tests はこの挙動を対象とする。音声速度だけから安定性改善を断定しない。[slow-01 report](../../artifacts/voice-tests/persistent-flat-slow-01/report.json)

flat-10 は full persistent gate のうち、保持 60.009 秒、continue、STOP、有限 `forward8` の期限 STOP、no-revival を通過した。条件更新は有限指示の submit 93.580 s と 8 秒期限から 101.580 s に失効した後、101.669 s に分類されたため `stale_execution` として拒否された。約 89 ms の期限後であり、失効した execution を復活させない正しい拒否だが、条件更新 gate を PASS に読み替えない。runner wall 124.657 s、peak tree RSS 1,163,210,752 B、最初の FORWARD E2E 5,147.51 ms、cleanup 後 PID は空、port は解放済みである。[flat-10 runner metadata](../../artifacts/voice-tests/persistent-flat-10/runner-metadata.json)

## 実行条件と計測

Windows `windows-local` 構成で実行した。Brain endpoint は `127.0.0.1:18766`、Bridge TCP/control は `127.0.0.1:18770/18771`。backend は `MALECNS_EXPERIMENTAL`、mode は `LIVE`、dataset は `male-cns:v1.0`。記録上の `ready` は false のままであり、接続成功を ready と読み替えていない。

| Run | runner wall | peak tree RSS | Brain frame 最大 age | 音声→適用 E2E |
|---|---:|---:|---:|---:|
| persistent-01 | 54.547 s | 1,167,904,768 B | 192.46 ms | 5,127.83 ms |
| persistent-flat-01 | 127.422 s | 1,162,002,432 B | 402.86 ms | 6,417.51 ms |
| persistent-flat-02 | 101.391 s | 1,152,208,896 B | 206.96 ms | 7,239.13 ms |
| persistent-flat-06 | 99.453 s | 1,160,024,064 B | 278.15 ms | 5,513.26 ms（最初の FORWARD） |
| persistent-flat-07 | 127.250 s | 1,155,600,384 B | 275.84 ms | 7,119.59 ms（最初の FORWARD） |
| persistent-flat-08 | 110.031 s | 1,161,068,544 B | 305.13 ms | 5,232.48 ms（最初の FORWARD） |
| persistent-flat-09 | 99.328 s | 1,148,661,760 B | 318.68 ms | 5,300.08 ms（最初の FORWARD） |
| persistent-flat-10 | 124.657 s | 1,163,210,752 B | artifact 原本参照 | 5,147.51 ms（最初の FORWARD） |

各 run の Brain window は 500 ticks／50 ms。最終身体測定の sequence 系統計は sampled observations の一意な `(sessionId, sequence)` だけを母数にする。flat-06 の raw observations は 448 行、重複を除く Brain sequence は 433 個（15〜522）だった。一方、非ゼロ step wall 時間 442 標本は観測ごとの値で重複を含む。step wall p50 は 163.11 ms、p95 は 214.02 ms、最大は 385.61 ms。frame age p95 は 178.88 ms。ほかの run の未保存 p50/p95 を補完していない。

実行環境は Windows 10.0.26200、Bridge Python 3.10.12／aiohttp 3.14.3／psutil 7.2.2、Brain Python 3.10.12／NumPy 1.24.3／Numba 0.61.2／llvmlite 0.44.0。最新の通常・平面 Player の `Assembly-CSharp.dll` は同一 SHA-256 `2A8A5C7B7CF88E5B60AFE8D8720F76B88152EEABC4DA7C100BC24564B1C8EEA5` であり、通常 PlayScreenBuilder の build は成功している。fixture manifest SHA-256 は `eaf9451b43903ebfd5059d5551bedcb1e41247dfbefd637e2428e32999458980`。各 run は source、config、data、player artifact の SHA-256 を [flat-07 runner metadata](../../artifacts/voice-tests/persistent-flat-07/runner-metadata.json) に保存している。代表値は `Runtime/Config/local.json` `55d5d8b70c36eb0c8ad61fa1a55f952e392d1208b8eb343900ae6ff3a20f9c1d`、`Runtime/Config/profiles/windows-local.json` `73fd7735ec3e84a31214dbfab63b80535b102b1eed250992e48804a8d2aa0b4d` である。

## 未実施・次の gate

実マイク入力の受入れは未実施である。上記は synthetic fixture PCM の検証であり、物理マイクの capture/transmit 成功を示さない。

条件登録 clarification と条件更新の受理は残課題として記録する。主要プレイ経路に支障がない限り、この厳密 gate の未達だけでリリースを止めない。Live の transcript/delegation 診断は文字列や PCM を保存せず、カウンタと時刻だけを保存して判定する。

## handoff 実測

`persistent-handoff-01` は 3 秒 initial hold と「そのまま」を PASS したが、STOP は transcript「とどまって」・delegation なしで失敗した。3 秒 hold は 60 秒継続の証明には使わない。`persistent-handoff-02` は 6 cases PASS だった。c1–4 と c6 は client delegation、c5 `forward8` は transcript semantic 補完で有限 FORWARD を適用し、期限 STOP と no-revival、条件更新の期限保持まで通過した。microphone は false。runner wall 52.547 s、peak tree RSS 1,156,841,472 B、最初の FORWARD E2E 5,540.30 ms、最大 frame age 264.81 ms、player exception 0、cleanup 後の owned PID は空で port は解放済みである。原本 metadata は source 11、config 5、data 4、artifact/fixture hash を保存している。[handoff-02 runner metadata](../../artifacts/voice-tests/persistent-handoff-02/runner-metadata.json)

補完経路の unit 26 tests を含む全 153 unit tests は PASS したが、人間マイクと通常 Player の full persistent 60 秒補完経路受入れは未実施である。flat-10 は無闇に再試行しない。classification-02 の最初の起動は keyfile 未指定で RuntimeError となり API を実行しなかった。keyfile 指定後の確定 run は自動再試行 0、29 件中 28 件一致、追加 transcript 5 件 PASS であり、nudge の不一致を残して未合格である。