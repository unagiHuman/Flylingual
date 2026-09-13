Codexにそのまま渡せる形で、実装境界まで含めて整理します。

# Blind Sugar Run

## Flylingual プロトステージ実装設計書

対象リポジトリ：`unagiHuman/Flylingual`
対象：Windows Unity側を中心としたプロトタイプ
目的：ハッカソン向けVertical Slice
想定プレイ時間：10〜15分
優先順位：**遊べること > 会話が攻略に必要であること > 見栄え > 汎用化**

---

# 1. このプロトで証明したいこと

このプロトの目的は、単にハエをMaleCNS経由で歩かせることではない。

以下のゲーム体験が成立することを証明する。

> **プレイヤーにはゲーム世界が見えない。
> ハエには周囲が見える。
> プレイヤーはハエと会話して状況を理解し、ハエの脳へ指示を送り、砂糖まで誘導する。**

プレイヤーはステージの3D映像を通常は見られない。

代わりに、

* ハエの発話
* 字幕
* 聞き取ったプレイヤー発話
* 現在の行動Intent
* 最小限のNeural Link状態

だけを見る。

ハエはUnity上の外部視覚・接触センサーから得た局所情報をGPT Live経由で言語化する。

重要：

**MaleCNSそのものがUnity映像を認識している、と表現してはならない。**

構成は以下。

```text
Unity World
   ↓
External Vision / Body Sensors
   ↓
Local Observation
   ↓
GPT Live
   ↓
Fly speech
   ↓
Player speech
   ↓
Action Intent
   ↓
Existing 6 Action protocol
   ↓
MaleCNS
   ↓
BrainFrame
   ↓
Existing CPG / Physics Fly
```

External Vision Moduleは、ハエに後付けされた「外部視覚脳」としてゲーム内設定上説明する。

---

# 2. 絶対に守る実装境界

既存のMaleCNS・Brain decoder・TCP経路を壊さない。

以下は禁止。

* GPTが`forward`や`turn`を直接生成する
* GPT出力をそのままArticulationBodyへ渡す
* MaleCNSをバイパスして移動する
* GPTの人格や感情によって摩擦、脚力、Gripを変更する
* ステージ都合でMaleCNSのdecoderを調整する
* プロトステージのためにBrain側の神経モデルを変更する

身体制御は必ず既存経路を通す。

```text
Player command
→ Action
→ Mac MaleCNS
→ BrainFrame
→ Unity MotorDecoder / CPG
→ Physical Fly
```

既存Action：

```text
STOP
FORWARD
TURN_R
TURN_L
FORWARD_R
FORWARD_L
```

ステージ側はこの6 Actionだけを前提に設計する。

---

# 3. プロトのゲームループ

1サイクルは以下。

```text
ASK
↓
ハエが周囲を説明
↓
PLAYER DECIDES
↓
音声で指示
↓
ACTION
↓
MaleCNS
↓
身体が実際に動く
↓
ハエが新しい状況を観測
↓
必要なら再度会話
```

ゲームの中心はリアルタイム反射操作ではない。

**Observe → Discuss → Commit → Observe**

という低周波の意思決定ゲームにする。

MaleCNSには数百ms以上の反応時間があり、STOPにも余動がある。

これを欠点として隠すのではなく、

> 「早めに止まる」
> 「狭い場所へ入る前に向きを合わせる」

というゲームルールへ利用する。

---

# 4. プロトステージ全体

ステージは3 Challenge + Goal。

```text
[START AREA]
     |
     | tutorial
     v
[RULER ALIGN AREA]
     |
     | narrow ruler
     v
[BOOK PLATFORM]
     |
     +------ narrow shortcut -----+
     |                            |
     +------ wide safe route -----+
                                  |
                              [SUGAR PLATE]
```

プレイヤーにはこの形状を通常表示しない。

---

# 5. Challenge 1：Start Area

## 目的

プレイヤーに、

* 自分には世界が見えない
* ハエには見えている
* ハエに質問できる
* ハエへ移動指示できる

ことを理解させる。

## 地形

十分に広い平面。

目安：

```text
8B × 8B以上
```

B = 通常歩行時のハエの横幅。

落下の危険は置かない。

周囲にランドマークを3つ配置する。

例：

* 青い本
* 赤い鉛筆
* 定規

ハエが周囲について説明できる材料として使う。

## 最初の会話例

ハエ：

> 「聞こえる？」

プレイヤー：

> 「聞こえる。」

ハエ：

> 「なんだこれ……前に大きな青いものがある。左には細長い透明な板。」

プレイヤー：

> 「右は？」

ハエ：

> 「右は広い。すぐ近くに落ちる場所はなさそう。」

ここでプレイヤーに「Ask Fly」を学習させる。

## 学習対象

* FORWARD
* TURN_L
* TURN_R
* STOP
* 周囲について質問する

---

# 6. Challenge 2：Ruler Bridge

このプロトで最も重要な難所。

## 目的

**ハエの情報を聞かないと危険な場所**を作る。

プレイヤーは橋を見ることができない。

ハエが説明する。

## 地形構造

```text
広いAlign Area
      \
       \ 接続角あり
        ========= ruler =========
                                  \
                                   Book Platform
```

橋入口を進行方向に対して少しずらす。

そのため単純FORWARDでは安全に入れない。

橋上で大きく旋回すると落ちやすい。

## 初期寸法

Align Area：

```text
6B × 6B以上
```

Ruler：

```text
幅 2.5〜3B
長さ 8〜12L
```

L = ハエ体長。

最初は水平。

傾斜は物理安定後に0〜5度程度で検証する。

## 橋下

広いBook Catch Platformを配置。

橋から落下しても即ゲームオーバーにはしない。

```text
Ruler
============

       ↓ fall

████████████████
 Open Book Catch
```

落下後、短時間で再挑戦可能にする。

---

# 7. Ruler Bridgeの理想的な会話

入口：

プレイヤー：

> 「前はどうなってる？」

ハエ：

> 「細い板がある。その先に大きな本。板は少し右を向いてる。」

プレイヤー：

> 「今の向きで渡れそう？」

ハエ：

> 「少し左に向いた方が真ん中に入りやすそう。」

プレイヤー：

> 「左を向いて。」

MaleCNS：

```text
TURN_L
```

ハエ：

> 「もう少し。」

プレイヤー：

> 「左。」

その後：

> 「どう？」

ハエ：

> 「だいたい正面。」

プレイヤー：

> 「進もう。」

```text
FORWARD
```

橋上：

ハエ：

> 「右側が近い。」

プレイヤー：

> 「止まって。」

ここでSTOPの遅延がゲームになる。

---

# 8. Challenge 3：Blind Branch

Rulerを渡った先に2ルートを置く。

```text
                    Sugar
                      ↑
            narrow ───┘
           /
Book ─────●
           \
            ───────── wide
```

## 左ルート

短い。

狭い。

危険。

## 右ルート

長い。

広い。

安全。

## ハエの説明

プレイヤー：

> 「この先は？」

ハエ：

> 「道が二つある。」

> 「左は近いけど細い。」

> 「右は遠回りだけど広い。」

ここではGPTに「どちらが正解」と言わせない。

ハエは観測可能な情報だけ説明する。

プレイヤーが選択する。

---

# 9. Goal：Sugar Plate

最後は広い皿。

プレイヤーにはまだ見えない。

ハエ：

> 「白い皿みたいなのがある。」

少し進む。

ハエ：

> 「甘い匂いがする。」

※匂いを使用する場合、Unity側にSugar proximity sensorを明示的に実装すること。

MaleCNSの神経状態から匂いを読み取ったことにはしない。

## Clear条件

Sugar Goal Triggerへ入っただけではなく、

```text
inside goal
AND
body velocity < threshold
AND
angular velocity < threshold
AND
stableTime >= 1 sec
```

程度でクリア。

値は現在のPhysics Flyに合わせて調整する。

---

# 10. 最後のReveal

クリア時のみ、初めてプレイヤーへ3D世界を見せる。

```text
暗いNeural Link画面
        ↓
fade
        ↓
Game Camera
        ↓
今まで歩いた机全体
```

カメラをゆっくり引く。

見えるもの：

* Start Area
* 定規
* 落下用の本
* 分岐
* Sugar Plate
* 実際のハエ

狙い：

> 「こんなところを歩いていたのか」

という驚きを作る。

このRevealはプロトの重要な演出なので優先度高。

---

# 11. 通常ゲーム画面

プレイ中はWorld Cameraをプレイヤーへ表示しない。

UI例：

```text
┌───────────────────────────────┐
│         FLY NEURAL LINK       │
│                               │
│      [Neural activity FX]     │
│                               │
│ FLY                           │
│ 「右側がかなり近い。」          │
│                               │
│ YOU                           │
│ 「止まって」                   │
│                               │
│ ACTION : STOP                 │
│ BRAIN  : MALECNS              │
│ LINK   : CONNECTED             │
└───────────────────────────────┘
```

通常プレイヤーへBrainの生ログは出さない。

必要ならDebug toggleを用意する。

---

# 12. External Vision Module

新規実装する。

推奨Component：

```text
FlyExternalVisionSensor
```

Fly headまたはThorax基準。

## 最初のプロトでは画像認識をしない

Camera画像をGPT Visionへ投げる構成は後回し。

ハッカソン版はUnity Physics queryで十分。

使用候補：

```text
Physics.Raycast
Physics.SphereCast
Physics.Raycast downward
Physics.OverlapSphere
Collider bounds
Trigger volumes
```

---

# 13. Observationデータ

新規struct/class例：

```text
FlyWorldObservation
```

概念データ：

```json
{
  "timestamp": 0.0,
  "ground": {
    "present": true,
    "surface": "ruler",
    "slopeDegrees": 2.1
  },
  "forward": {
    "object": "book",
    "distance": 0.38
  },
  "left": {
    "edgeDistance": 0.08
  },
  "right": {
    "edgeDistance": 0.025
  },
  "landmarks": [
    {
      "name": "blue_book",
      "direction": "forward_left",
      "distance": 0.42
    }
  ],
  "body": {
    "speed": 0.04,
    "turnRate": -3.4,
    "stable": false
  }
}
```

実装はこの完全形である必要はない。

最低限：

* ground存在
* slope
* left edge距離
* right edge距離
* forward obstacle / platform
* landmark
* body moving/stable

を取る。

---

# 14. Edge Detection

橋攻略で重要。

左右方向にDown Rayを複数投射する。

例：

```text
        Forward

   L2 L1 Fly R1 R2
    ↓ ↓  🪰  ↓ ↓
```

Rayがgroundへ当たらなくなる位置からedge距離を推定。

完璧な幾何解析は不要。

ゲーム用の離散カテゴリでもよい。

```text
SAFE
NEAR
VERY_NEAR
NO_GROUND
```

例えば：

```text
> 2B   SAFE
1〜2B  NEAR
< 1B   VERY_NEAR
```

実際のFlyサイズに合わせて調整する。

---

# 15. Landmark System

ステージオブジェクトに、

```text
FlyLandmark
```

Componentを付ける。

例：

```text
BlueBook
RulerBridge
OpenBookCatch
RedPencil
SugarPlate
```

フィールド例：

```text
landmarkId
spokenName
category
```

GPTへ渡す際、

```text
"blue_book"
```

ではなく、

```text
「大きな青い本」
```

のような自然言語用ラベルも持たせる。

---

# 16. ハエが知ってよい情報

External Visionから渡してよい：

* 自分の近くの足場
* 崖までのおおよその距離
* 正面の物体
* 左右に何があるか
* 表面傾斜
* 現在動いているか
* 現在旋回しているか
* Grip/contact
* 近距離ランドマーク

---

# 17. ハエが知ってはいけない情報

GPTへ以下を渡さない。

* ステージ全体NavMesh
* Goalへの最短ルート
* 未訪問エリア全体
* Level designerが設定した正解ルート
* プレイヤーから見えない遠距離情報
* Cheat用のtransform一覧

GPTが、

> 「右へ3m、そのあと左でゴール」

などと言えない構造にする。

---

# 18. Observation範囲

ハエの認識は局所に限定。

推奨：

```text
radius = 数体長〜十数体長
```

Stage全体をOverlap検索しない。

Landmarkも一定距離以内のみ。

視線方向が必要なものはFOVを設定してよい。

---

# 19. GPT Liveとの責務分離

GPTの仕事：

```text
Observation
→ human-readable description
```

および、

```text
Player utterance
→ conversational response
→ optional Action Intent
```

GPTの仕事ではない：

```text
Physics control
Motor generation
Route solving
Brain simulation
```

---

# 20. Action Intent

GPTからUnityへ返すActionは必ず既存6 Actionへ正規化。

例：

Player：

> 「ちょっと右向いて。」

↓

```text
TURN_R
```

Player：

> 「前に進みながら右へ。」

↓

```text
FORWARD_R
```

Player：

> 「待って。」

↓

```text
STOP
```

---

# 21. 会話と移動命令の区別

重要。

以下はActionにしない。

> 「右って危ない？」

> 「右に行った方がいいかな？」

> 「右側はどう？」

これらは質問。

Action発火は禁止。

以下はAction。

> 「右向いて。」

> 「右へ行こう。」

> 「少し右。」

曖昧な場合：

```text
Action = NONE
```

ハエ：

> 「右へ動くってことでいい？」

---

# 22. Safety

曖昧な指示で勝手に進ませない。

以下の場合、

```text
STOP
```

または現在Actionを更新しない。

* speech parse失敗
* GPT timeout
* connection loss
* unknown command
* stale response

古いGPT Actionを遅れて適用しない。

Actionにはrequest ID / timestampを持たせることを推奨。

---

# 23. 緊急停止

Normal STOPとは別。

UIに：

```text
EMERGENCY MOTOR CUT
```

を用意する。

Keyboard fallback例：

```text
Space
```

Emergency Motor Cut：

* motor requestを即STOPへ
* 新Action送信抑止
* 身体位置固定は禁止
* velocity zero強制禁止
* teleport禁止
* Grip強制成功禁止

つまり物理的な慣性・落下は残す。

---

# 24. Memory

プロトでは非常に小さくする。

保存対象：

```text
lastFallLocation
lastActionBeforeFall
lastFailureObservation
chosenRoute
playerNamedLandmarks
```

最初のプロトでは、

```text
lastFallLocation
lastActionBeforeFall
```

だけでもよい。

落下後：

> 「さっきは橋の上で右に曲がってる途中で落ちた。」

のように一度だけ使う。

---

# 25. Fall Detection

新規Component候補：

```text
FlyFallTracker
```

検出：

* sudden Y decrease
* Kill/Recovery Trigger
* Catch Platform Trigger

落下時に記録：

```text
position
lastAction
lastObservation
timestamp
```

GPTへ渡せる。

---

# 26. Failure後の会話

原因を断定しない。

悪い例：

> 「右脚の摩擦不足が原因だよ。」

測定していないなら禁止。

良い例：

> 「右側に寄っていて、曲がっている途中で落ちた。」

観測事実だけ。

または：

> 「橋の上で曲がるのは難しそう。入口で向きを合わせて試す？」

---

# 27. Debug / Spectator Camera

開発中はステージが見えないとデバッグ不能なので、

```text
Developer Spectator Mode
```

を必ず作る。

例：

```text
F1 = Blind Player View
F2 = Spectator View
F3 = Sensor Debug View
```

本番デフォルト：

```text
Blind Player View
```

---

# 28. Sensor Debug

Scene View / Game Viewで以下を可視化可能にする。

* raycasts
* edge detections
* landmark range
* current observation text
* current Action
* BrainFrame forward/turn

本番ではOFF。

---

# 29. Scene Hierarchy案

新規Scene：

```text
BlindSugarRunPrototype.unity
```

概念Hierarchy：

```text
BlindSugarRunPrototype
├─ Systems
│  ├─ GameFlowController
│  ├─ ConversationController
│  ├─ ObservationController
│  ├─ ActionIntentRouter
│  ├─ BrainIntegration
│  └─ PrototypeMemory
│
├─ Fly
│  ├─ ExistingPhysicsRig
│  ├─ ExternalVisionSensor
│  ├─ FallTracker
│  └─ LandmarkSensor
│
├─ Level
│  ├─ StartArea
│  ├─ AlignArea
│  ├─ RulerBridge
│  ├─ OpenBookCatch
│  ├─ BookPlatform
│  ├─ NarrowRoute
│  ├─ WideRoute
│  └─ SugarPlate
│
├─ Cameras
│  ├─ HiddenWorldCamera
│  └─ SpectatorCamera
│
└─ UI
   ├─ BlindPlayerHUD
   ├─ SubtitlePanel
   ├─ PlayerTranscript
   ├─ CurrentIntent
   ├─ NeuralLinkStatus
   └─ EmergencyStop
```

既存のFly/Brain prefabがある場合、新規コピーを作らず可能な限り再利用する。

---

# 30. 推奨スクリプト構成

新規コードは可能なら：

```text
UnityProject/Assets/Flylingual/PrototypeBlindRun/
```

以下へ分離。

```text
Runtime/
├─ BlindRunGameFlowController.cs
├─ FlyExternalVisionSensor.cs
├─ FlyWorldObservation.cs
├─ FlyLandmark.cs
├─ FlyFallTracker.cs
├─ BlindRunMemory.cs
├─ ActionIntentRouter.cs
└─ BlindRunGoal.cs

UI/
├─ BlindRunHud.cs
├─ ObservationDebugHud.cs
└─ BlindRunViewModeController.cs

Editor/
└─ BlindRunSensorGizmos.cs
```

既存project structureが明確に異なる場合は、それに従う。

---

# 31. Game Flow State

状態を明示する。

```text
BOOT
↓
CONNECTED
↓
INTRO
↓
PLAYING
↓
FALL_RECOVERY
↓
PLAYING
↓
GOAL
↓
REVEAL
↓
COMPLETE
```

Brain disconnected時：

```text
PLAYING
→ CONNECTION_ERROR
```

勝手にMockへfallbackしない。

実Brain利用中であることを明確にする。

---

# 32. Conversation状態

少なくとも：

```text
LISTENING
THINKING
SPEAKING
ACTION_PENDING
```

をUIへ出せるようにする。

プレイヤーが、

> 「聞き取られたのか」
> 「Brainがまだ動いているのか」

を区別できるようにする。

---

# 33. Neural Link演出

通常画面の中央または背景に、

* pulse
* node graph
* waveform
* MaleCNS activity

の簡易ビジュアルを表示してよい。

ただし実データと演出データを混同しない。

実値を出せる部分：

* current Action
* BrainFrame forward
* BrainFrame turn
* sequence
* backend
* connection

演出のみの場合、

```text
decorative visualization
```

としてコード上も分離する。

---

# 34. 音

最小限必要：

* fly footsteps
* ruler footsteps
* book footsteps
* falling
* landing
* neural link connect
* sugar goal

Bridgeでは音で危険感を補助する。

プレイヤーは画面が見えないため、音響の重要度が通常ゲームより高い。

---

# 35. 空間音響

可能ならハエの環境音を左右定位する。

例：

右側にedge → 小さな環境音ではなく、足音や接触音の反射を利用。

ただしハッカソンでは後回し。

最初は会話＋字幕で成立させる。

---

# 36. MVP実装順

## Phase 1：Worldだけ作る

GPTなし。

MaleCNSなしでもよい。

Spectator Viewで：

```text
Start
→ Ruler
→ Branch
→ Sugar
```

を既存Flyで歩けることを確認。

---

## Phase 2：実Brain

Live MaleCNS接続。

6 Actionで、

```text
Start
→ Ruler
→ Goal
```

を人間がDebug viewを見ながら操作できることを確認。

ここで物理成立性を先に取る。

---

## Phase 3：External Vision

Raycast sensor追加。

Debug画面に：

```text
RIGHT EDGE: 0.03m
LEFT EDGE: 0.10m
FORWARD: RULER
```

等を表示。

正しいかSpectatorで比較。

---

## Phase 4：Blind UI

World Cameraを消す。

テキストObservationだけで開発者自身が進めるか確認。

この時点ではGPT不要。

ルールベースで：

```text
「右側が近い」
「前に定規がある」
```

を表示してよい。

---

## Phase 5：GPT Live

ObservationをGPT Liveへ渡す。

自然な会話へ変換。

同時にplayer speech → 6 Action conversionを接続。

---

## Phase 6：Memory

1回の落下を記憶。

再挑戦時だけ、

> 「さっきは〜」

を追加。

---

## Phase 7：Reveal

Goal後に初めてworld cameraを表示。

---

# 37. 最初にGPTへ渡すSystem Rule

概念として以下を守らせる。

```text
You are a small fruit fly connected to an external visual module.

You can only know the local observations explicitly supplied to you.

Never invent distant terrain, hidden routes, or the correct path.

Describe nearby terrain briefly and concretely.

The player cannot see the world and must rely on your descriptions.

During movement, keep responses extremely short.

When asked a question, answer only from observed data.

Never claim that your biological brain itself sees Unity camera data.
The external vision module provides this information.

Do not directly control the body.
Only return one of the allowed action intents when the player gives a clear movement command.

Allowed actions:
STOP
FORWARD
TURN_R
TURN_L
FORWARD_R
FORWARD_L
NONE

Questions, speculation, and discussion must return NONE.

When uncertain about a command, ask for confirmation rather than moving.
```

最終prompt wordingは既存GPT Live実装へ合わせる。

---

# 38. Action response contract

可能なら自然言語だけで解析しない。

GPTから構造化結果を得る。

概念：

```json
{
  "speech": "少し右を向くね。",
  "action": "TURN_R"
}
```

質問の場合：

```json
{
  "speech": "右側はかなり近いよ。",
  "action": "NONE"
}
```

Unityは`action`だけをActionIntentRouterへ渡す。

---

# 39. Prototype Acceptance Criteria

以下をすべて満たせばプロト成立。

## Physics

* StartからSugarまで実Brainで到達可能
* TURN_L/Rに恒常的な逆旋回がない
* STOP可能
* Ruler上で操作可能
* 落下後に継続可能

## External Vision

プレイヤー映像OFF状態で、

* 前方足場を説明できる
* 左右edgeを説明できる
* 分岐を説明できる
* Sugar近辺を説明できる

## Conversation

プレイヤーが、

> 「右は？」

と聞いても移動しない。

プレイヤーが、

> 「右を向いて。」

と言った場合のみTURN_R。

曖昧入力では勝手に動かない。

## Blind Play

開発者がSpectator Viewを見ずに、

```text
Start
→ Ruler
→ Branch
→ Sugar
```

を最低1回クリアできる。

## Core Game Test

Rulerで一度失敗した後、

ハエの説明・振り返りによって二度目の行動が変化する。

これが最重要。

---

# 40. ハッカソン用完成条件

以下が揃えば十分。

```text
[必須]
✓ MaleCNS Live
✓ Physical Fly
✓ Blind Player View
✓ External Vision
✓ Voice conversation
✓ Ruler challenge
✓ One route decision
✓ Fall + retry
✓ Sugar goal
✓ Final reveal
```

以下は後回し。

```text
[非必須]
× 長期人格成長
× 6区間フルコース
× Unity映像のGPT Vision解析
× 完全な空間認識
× Fly biological visual system simulation
× 動的風
× 壁歩行
× 天井歩行
× 飛行
× procedural stage
```

---

# 41. Codexへの重要な判断基準

迷った場合は以下を優先する。

1. 既存MaleCNS integrationを壊さない
2. プレイヤーにはステージを見せない
3. ハエは局所情報しか知らない
4. GPTに正解ルートを教えない
5. 操作は既存6 Actionだけ
6. まず定規橋を面白くする
7. 技術的に複雑な画像認識よりRaycastを選ぶ
8. 落下をバグ扱いせずゲームプレイにする
9. ただし通信・AI障害による落下はゲーム失敗扱いにしない
10. 最後のRevealを必ず残す

---

# 42. このプロトの完成イメージ

プレイヤー画面は世界が見えない。

ハエ：

> 「前に細い板がある。右側が落ちてる。」

プレイヤー：

> 「少し左。」

ハエ：

> 「うん。」

MaleCNSが反応し、物理身体が旋回する。

ハエ：

> 「今は真ん中に近い。」

プレイヤー：

> 「前へ。」

橋を進む。

ハエ：

> 「待って、右に寄ってる。」

プレイヤー：

> 「止まって！」

身体は少し余動する。

落ちる。

ハエ：

> 「……落ちた。」

プレイヤー：

> 「何が悪かった？」

ハエ：

> 「橋の上で右に寄ってた。次は入る前にもう少し左を向く？」

再挑戦。

今度は成功する。

最後に：

> 「甘い匂いがする。」

Sugar到達。

そして初めてカメラが開き、

**プレイヤーは自分がどんな場所をハエと一緒に進んできたのかを見る。**

これをBlind Sugar Runプロトの完成形とする。

この設計なら、Codexにはまず **Phase 1〜4までを一気に実装させ、GPT Liveは後から載せる**のが安全です。これにより「ステージ自体が面白いか」と「AI会話が動くか」を分離して検証できます。
