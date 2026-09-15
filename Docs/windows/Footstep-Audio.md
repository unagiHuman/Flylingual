# ハエの足音

FlyFootstepAudioは接地中の実身体移動量に応じて、小さなカサッ・コツッという3種類の合成足音を再生する。初期歩幅0.12m、最大10回/秒、音量0.14。静止時の揺れを除外し、タイトル・ポーズ・GameOver・接続待ち・空中では停止する。操作意図から足音やmotorを生成しない。

専用AudioSourceのAudioReverbFilterにUser設定、decayTime=0.65秒、room=-1000、reverbLevel=-800を設定。会話や他のSEにはフィルターを掛けない。SEManagerの音量とMixerGroupを使い、発話中は足音を45%へ下げる。外部音素材は使用していない。

## 2026-09-14 検証

Unity Editor、Windows実Brain 127.0.0.1:18766、MALECNS_EXPERIMENTAL、raw ready=false、fresh=true。通常のテキスト指示「前に進んで」「止まって」で確認。

- 初期静止3秒：足音0回。
- 前進約5秒、z約0→4.69m：足音36回。
- 停止指示後3秒：36回のままで追加なし。
- sequence71→138。専用リバーブenabled=true、User、decay=0.65、room=-1000、wet=-800を確認。

証拠：artifacts/footsteps-20260914/samples.csv、reverb.txt。これは再生処理と設定の実測であり、出力音の聴感・リバーブ尾の録音確認は未実施。空中・Retryの再試行は未実施。
