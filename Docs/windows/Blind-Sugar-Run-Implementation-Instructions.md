# Blind Sugar Run — Astra向け実装指示書

対象：`unagiHuman/Flylingual`\
目的：ハッカソン用10〜15分Vertical Slice

## 1. ゲームの核

プレイヤーには3Dステージを見せない。

ハエだけがUnity上の局所センサーから周囲を認識し、GPT Liveを通じてプレイヤーへ説明する。

プレイヤーは会話で状況を把握し、ハエへ移動を指示して砂糖を目指す。
```text
Unity local sensors
→ GPT Live
→ ハエの説明
→ Player speech
→ Action
→ MaleCNS
→ BrainFrame
→ CPG / PhysX Fly
```

MaleCNS自体がUnity映像を見ている、とは扱わない。

外部視覚モジュールをハエへ接続している、というゲーム設定にする。

---

## 2. 絶対に守ること

既存のBrain経路を変更しない。

身体操作は必ず既存6 Actionを使う。
```text
STOP
FORWARD
TURN_R
TURN_L
FORWARD_R
FORWARD_L
```

禁止：

- GPTからforward/turnを直接生成
- GPTから物理bodyを直接操作
- MaleCNS bypass
- ステージ都合でBrain decoderを変更
- GPTにステージ全体や正解ルートを渡す

既存PhysicsRig / CPG / MotorDecoderも、必要性を確認せず変更しない。

---

## 3. プロトステージ

1ステージだけ作る。
```text
Start Area
    ↓
Ruler Alignment Area
    ↓
Ruler Bridge
    ↓
Book Platform
   ↙       ↘
狭い近道   広い迂回路
   ↘       ↙
    Sugar Goal
```

### Start Area

広い安全地帯。

ここで、

- 前進
- 左右旋回
- STOP
- ハエへ周囲を質問

を学ぶ。

### Ruler Bridge

プロトの中心。

橋は少し斜めにつなぎ、入る前に方向を合わせる必要がある。

ハエ：

> 「前に細い板がある。少し右を向いてる。」

プレイヤー：

> 「少し左。」

橋の上では端との距離をハエが短く報告する。

STOPには遅延と余動があるため、早めに止まること自体を攻略要素にする。

### Branch

2ルート。

- 狭いが短い
- 広いが遠い

ハエは特徴だけを説明する。

どちらを選ぶべきかはプレイヤーが判断する。

### Sugar Goal

砂糖のある皿へ到達し、身体が一定時間安定したらクリア。

---

## 4. External Vision

最初は画像認識を使わない。

Unity Physics queryで局所観測を作る。

最低限取得する：

- 正面に何があるか
- 正面までのおおよその距離
- 左右のedgeまでの距離
- 現在のground
- slope
- 近距離landmark
- body moving / stable

GPTへ渡すのはハエ近傍だけ。

ステージ全体、未訪問領域、最短ルートは渡さない。

---

## 5. GPT Live

GPTの役割は2つだけ。

### A. 観測を自然言語化

例：
```text
rightEdge = very_near
forward = ruler
```

↓

> 「右側がかなり近い。前には細い板が続いてる。」

### B. プレイヤーの明確な移動命令を6 Actionへ変換
```text
「右を向いて」
→ TURN_R
```

ただし、
```text
「右は危ない？」
→ NONE
```

質問や相談を勝手に移動命令へ変換しない。

曖昧なら確認する。

---

## 6. Blind UI

通常プレイ中はWorld Cameraを見せない。

表示するのは最低限：

- ハエの発話
- Player transcript
- Current Action
- Brain connection state
- Listening / Thinking / Speaking状態

Developer ModeのみWorld CameraとSensor Debugを表示できるようにする。

---

## 7. 落下

落下はゲームプレイとして扱う。

落下したら、

- 直前の場所
- 直前のAction
- 観測できた状況

だけを記憶する。

再挑戦時に一度だけ会話へ利用してよい。

例：

> 「前は橋の右側に寄ってる途中で落ちたね。」

観測していない原因をGPTに断定させない。

通信障害やGPT障害による失敗は通常のゲーム失敗として扱わない。

---

## 8. Final Reveal

Sugarへ到達したら、初めて3Dステージをプレイヤーへ見せる。
```text
Blind HUD
→ Fade
→ World Camera
→ Camera pull back
→ 今まで歩いたコース全体
```

「こんな場所を歩いていたのか」と感じさせることが目的。

この演出は削らない。

---

## 9. 実装順

以下の順番を守る。

### Phase 1

Unity primitiveだけでステージを作る。

Developer ViewでStart → Sugarを既存Flyが通過可能にする。

### Phase 2

Windows実Brainを接続する。

既存6 Actionだけでコースを完走可能にする。

### Phase 3

External Visionを実装する。

Developer Viewでsensor値が実際の地形と一致することを確認する。

### Phase 4

Blind UIを実装する。

最初はGPTなしでもよい。ルールベース文章でBlind状態から進めるか確認する。

### Phase 5

GPT Liveを接続する。

Observation → speechと、Player speech → Actionを統合する。

### Phase 6

落下記憶を追加する。

### Phase 7

Final Revealと最低限の美術・音を追加する。

---

## 10. 最重要Acceptance

以下を満たせばプロト成立。

1. Windows実BrainでStartからSugarまで到達できる。
2. プレイヤーはWorld Cameraを見なくても進める。
3. ハエは前方・左右edge・分岐を説明できる。
4. 質問では身体が動かない。
5. 明確な命令だけ6 Actionへ変換される。
6. 一度失敗した後、ハエの説明を参考に二度目の行動を変えられる。
7. Sugar到達後にFinal Revealが再生される。

特に重要なのは、

> **Ruler Bridgeで一度失敗し、会話によって二度目の攻略方法が変わること。**

ここが成立すれば、Blind Sugar Runのゲームコンセプトは成立したと判断する。

---

## 11. Astraへの作業方針

最初から全機能を同時に作らない。

まず既存リポジトリを調査し、

- 既存Fly prefab
- Brain integration
- GPT Live integration
- Scene
- UI
- Action routing

を特定する。

既存機能を再実装しない。

その後、上記Phase単位で実装・検証する。

各Phaseの完了時に、

- 変更ファイル
- 実施した検証
- 成功したこと
- 未検証事項
- blocker

を簡潔に報告する。

ハッカソンでは汎用化より、**Blind状態で定規橋を会話攻略できるVertical Sliceの完成を優先する。**
