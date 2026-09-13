# 足場を失ったときの保持解除

2026-09-14。崖の接近で停止する仕様には戻さず、安定した支持を失ったときに接着と地形用の足位置保持を解除する。

変更は `FlyFootContact.cs`、`FlyFootAdhesion.cs`、`FlyTerrainTraversal.cs`。

- 接触通知は対象FootPadのColliderを厳密に照合する。Articulationから届く他部位の接触を、その足の支持として数えない。
- 新鮮な実Brainと地形観測がある状態で、直下足場なし＋上向きの実足支持が3本未満の状態が0.3秒続くと解除する。通常のSTOP中も判定する。
- 解除中は全足の接着力を抑止し、過去の着地点と危険姿勢の角度保持を捨てる。外力・瞬間移動・重力変更・関節強度変更は行わない。
- 実支持が3本に戻る、または直下足場と実足接触が戻ると通常動作へ復帰する。通常の三脚支持・一時的な踏み替えだけでは発動しない。
- 接続不良による既存の物理休止は維持。実Colliderで身体が支持されている状態は強制的に床抜けさせず、停滞時の20秒ハエたたきも維持する。

## 実プレイ検証

Unity Editor 6000.5.9f1、Windows実Brain `127.0.0.1:18766`、backend `MALECNS_EXPERIMENTAL`、raw ready=false。通常のテキスト操作→Bridge→実Brain→PhysXを使用。Replay/mock/motor上書きなし。

1. 「40m前に進んで」：平地歩行に誤発動なし。橋付近で支持0が継続し解除。解除中は全足Attached=false・接着力0。再接地で通常状態へ復帰し、橋上で停止したあとハエたたきGameOver。胴体等の実Collider支持が残る場合には接着解除だけで落下しないことも記録した。
2. Retry→前進→通常右旋回→前進：橋外で支持1の状態が0.32秒続き保持解除。高さ0.75付近から落下し、位置 `(9.09,-2.06,32.64)` で既存の落下GameOverを確認。ハエたたきによる死亡ではない。

証拠: `artifacts/natural-fall-20260914/` の試行コード、JSONL、画像、events.json。試行2では落下途中に接続の一時休止もあり、終了直後のHasFreshBrain=falseを成功値に置き換えていない。GameOverへの分類時点は既存Sessionのhealthy条件を通過している。

この修正が過去のすべての引っかかりを解消したとは断定しない。保持解除・再接地・自然落下・既存GameOverへの接続を確認した。更新後Player自体の再プレイは未実施。

正式Windows Playerを2026-09-14 00:10 JSTに更新。ビルドSucceeded、25.76秒、error0／warning36。Editorの最終コンパイルもエラーなし。試行2の記録336標本中fresh332、stale4、sequence0→942。解除中の6標本は接着力合計0。EditorはEdit Modeで終了。
