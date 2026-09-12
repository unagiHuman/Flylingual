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

>
