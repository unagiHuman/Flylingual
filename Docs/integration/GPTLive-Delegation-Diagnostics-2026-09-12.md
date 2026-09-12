# GPT Live Delegation Diagnostics

更新日: 2026-09-12。対象は Flylingual Bridge の現行 `ConversationAdapter`、
`Bridge.voice_utterance`、intent translation、ja/en delegation policy である。
本書は [Bridge v1 protocol](../../Contracts/bridge-v1/protocol.md) の
`audioDiagnostics` 拡張を説明する。API、ブラウザ、プロセス、Unity、Gitの実行は行っていない。

## 診断キーと恒等式

追加される delegation/transcript の10キーは次のとおり。既存の
`delegationCount` と `inputTranscriptDeltas` はこの10個とは別の既存キーである。

- raw: `delegationEventsSeen`
- reject 5分類: `delegationRejectedShape`、`delegationRejectedTarget`、
  `delegationRejectedId`、`delegationRejectedDuplicate`、
  `delegationRejectedOffset`
- transcript timing: `timedInputTranscriptDeltas`、
  `untimedInputTranscriptDeltas`
- accepted後の transcript 有無: `delegationWithTranscript`、
  `delegationWithoutTranscript`

必須の会計恒等式は次のとおり。

```text
raw = accepted + 5 reject classes
accepted = With + Without
inputTranscriptDeltas = timedInputTranscriptDeltas + untimedInputTranscriptDeltas
```

`delegationCount` は client target、ID長、重複、有限 offset の検査を全て通過した受理イベントだけを数える。受理後に transcript が結び付いたかどうかを With/Without で分ける。`timedInputTranscriptDeltas` と `untimedInputTranscriptDeltas` は ASR transcript の時刻情報分類であり、delegation受理やAction適用を意味しない。

診断値は live session start でresetする。context clear と conversation stop は queue をdrainするが、そのsessionのカウンタは保持し、次のsession startで新しい値にする。本文、PCM、delegation IDは診断値や永続通常ログへ保存しない。一方、Bridge生成のvoice command IDは `voice_intent_dispatch` / `intent_classified` の相関用serverログへ記録される。重複拒否のためのboundedな一時メモリdelegation IDは外部へ出さず、証拠として扱わない。

## 処理と安全境界

`conversation_prompts.py` の日本語・英語ポリシーは、操作要求とBrain質問を明示的に client delegation へ渡し、挨拶・雑談・既知結果の反復はdelegationしない。設定言語 `ja` / `en` は応答言語を固定するだけで、安全規則・owner・6 Actionを変更しない。ASR transcriptからの自動Actionフォールバックはない。delegationが無い、形が不正、stale context、旧epoch、fresh STOP gate未成立の場合は操作を開始・完了扱いにしない。

server側の安全ログ outcome は `voice_intent_dispatch` の `started`、`rejected`、`stale_context` に限定される。`intent_classified` は Responses の schema 検証直後、epoch/TTL・owner・freshness・voice session gate の前に記録される検証済み proposal の `kind` / `action` と `source`（voice/text）であり、適用成功を意味しない。受付・Brain適用・神経応答・実身体動作を同一視せず、epoch、freshness、owner、output inhibition、期限、Brain適用確認の安全gateを維持する。

会話APIのプロンプト設計は、公式の [Live prompting](https://developers.openai.com/api/docs/guides/live-prompting) と [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation) を参照する。これは現コードの安全境界と診断分類を説明するもので、実API受入れを証明しない。

## 実測・未実施

先行ユーザーtrialで観測済みなのは `inputTranscriptDeltas=13`、
`delegationCount=0` のみである。raw delegation events と5分類の内訳はそのtrialで採取されておらず、`delegationEventsSeen` の有無を遡って断定しない。

今回、実API接続、Bridge再起動、現コードの稼働反映確認、Windows Unity、実身体は未実施であり、`ready=false` を維持する。Unity接続実行と再起動確認は、統合担当の本人環境回答待ちで保留している。既存のマイク修正検証文書 [GPTLive-Microphone-Fix-2026-09-12](GPTLive-Microphone-Fix-2026-09-12.md) の証拠・結論は書き換えない。
