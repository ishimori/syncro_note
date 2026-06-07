# models/

話者埋め込み等の ONNX モデル置き場（DD-004-1）。**モデル本体（`*.onnx`）は Git 管理外**（リポジトリ肥大化回避・`.gitignore` の `*.onnx`）。下記手順で各自DLする。初回DLのみネット接続が必要で、**DL後は完全オフライン**で動作する。

## 話者埋め込み: 3D-Speaker CAM++（DD-004-1 の本命手法）

- ファイル: `campplus_sv_zh-cn_16k-common.onnx`（約27MB, 出力192次元埋め込み, 入力80次元fbank）
- 配布: sherpa-onnx リリース（Apache-2.0・HuggingFace gate なし）
- 入手:

```bash
# python/ で実行
curl -L -o models/campplus_sv_zh-cn_16k-common.onnx \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
```

> 別パスに置く場合は環境変数 `SYNCHRONI_SPK_MODEL` で上書き可（`diarization/embedding_onnx.py`）。
> 特徴抽出は `kaldi-native-fbank`（CAM++学習時と同じKaldi仕様）、推論は `onnxruntime`(CPU)。
> 製品期は Rust `ort` crate で同じ ONNX を実行（地続き）。
