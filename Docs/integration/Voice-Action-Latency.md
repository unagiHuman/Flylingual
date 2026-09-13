# 音声 Action レイテンシ仕様

2026-09-13。目的は、停止精度よりも明確な移動指示で進める操作感を優先しつつ、曖昧な発話を勝手に実行しないことである。実測結果は [Voice Action Latency 検証記録](../windows/Voice-Action-Latency-20260913.md) に分ける。本書は実装仕様であり、通常 Player の受入れ成功を主張しない。

## 高速に受理する範囲

`fast_intents.py` は厳密な全文 grammar に一致する単純な日英の指示を直接 proposal にする。対象は既存6 ActionのうちFORWARD、STOP、TURN_R、TURN_Lと、明確な秒数、距離、nudgeである。この範囲では追加 LLM 呼出しを省略する。距離は既存の distance 規則に従う。

unknown、曖昧表現、否定、質問、訂正、条件、継続・更新は高速経路へ入れず、既存 `interpret_intent` の Responses／ollama 設定へ渡す。音声本体は GPT Live を維持し、Brain、decoder、CPG、Physics、motor 経路を変更しない。

## 発話境界と重複防止

従来の一律1秒の transcript batch を、最終有声音声から300 ms静かで、かつ0.25秒安定した transcript candidate の受付へ変更した。RMS は0.012以上を有声音声の条件に用いる。静かな区間が得られなくても、本文が1秒安定した場合は既存の意味解釈へ渡し、背景雑音で受付が無期限に待たされることを避ける。この場合は高速規則を使わない。これは Bridge 側の区切り heuristic であり、API の final event ではない。長い間を置いた言い直しまで一発話と判定する保証はない。

Live delegation と transcript は共通 candidate に統合する。`inputId` は会話世代と startMs から作り、受理時の `commandId` に引き継ぐ。同じ pending 分類中に delegation が届いても、同じ区間を再解釈せず一回だけ消費する。別の発話で同じ本文になった場合は別 utterance として扱う。

## 安全と観測

純粋 TURN だけは `forwardBlocked` を適用しない。freshness、ground、edge、body safety は引き続き必須である。TURN の後に FORWARD へ移る計画は前進直前にもう一度安全観測を検査する。距離は対象、値、観測の既存 strict validation を緩めない。

観測には route（`rules` または `model`）、同一 inputId と commandId、推定 speech-end 時刻、classification start/end、Brain applied、Unity body onset を残す。これらはどの段階まで到達したかを分けるための診断であり、受付だけで身体移動を断定しない。

## 検証状況

オフライン unit tests は189件（89 + 99 + 雑音時フォールバック1）PASS。通常exeと実GPT Live、Windows Brainを通した合成音声試験で、前進・STOP・右旋回の3ケースが高速経路で成立した。4件目のあいまいな入力もモデル解釈から実移動したが、距離移動に旧来のTTL停止を要求する項目は未完了。試験全体のPASSとは扱わない。実マイクは今回未試験。測定条件と待ち時間は[検証記録](../windows/Voice-Action-Latency-20260913.md)を参照する。
