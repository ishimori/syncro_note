"""ONNX話者埋め込みによる話者分離（DD-004-1, 本命手法）。

simple-cluster の手作りMFCC特徴を、**訓練済みの話者埋め込みモデル**（3D-Speaker CAM++）の
192次元埋め込みに置き換える。VAD区間ごとに「声の指紋」を作り、コサイン空間でクラスタリングする。

構成（完全オフライン・追加モデルDLは初回のみ）:
- 特徴量: kaldi-native-fbank で 80次元 fbank（CAM++ の学習時と同じ Kaldi 仕様）→ 発話内平均で CMN
- 推論: onnxruntime(CPU) で CAM++ ONNX を実行 → 192次元 L2正規化埋め込み
- クラスタリング: simple-cluster と同じ numpy KMeans（埋め込みを L2正規化＝コサインKMeans 相当）

モデル: `python/models/campplus_sv_zh-cn_16k-common.onnx`（sherpa-onnx 配布, Apache, gateなし）。
未配置なら `models/README.md` の手順でDL。製品期は Rust `ort` crate で同 ONNX を実行（地続き）。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from synchroni_note.bench.vad_segment import detect_voiced_spans
from synchroni_note.diarization.base import SAMPLE_RATE, Turn
from synchroni_note.diarization.simple_cluster import _kmeans

_DEFAULT_MODEL = (
    Path(__file__).resolve().parents[3] / "models" / "campplus_sv_zh-cn_16k-common.onnx"
)


def _model_path() -> Path:
    return Path(os.environ.get("SYNCHRONI_SPK_MODEL", str(_DEFAULT_MODEL)))


def _fbank(samples: np.ndarray, sr: int) -> np.ndarray:
    """CAM++ 学習時と同じ Kaldi 80次元 fbank を返す（T,80）。"""
    import kaldi_native_fbank as knf

    opts = knf.FbankOptions()
    opts.frame_opts.samp_freq = float(sr)
    opts.frame_opts.dither = 0.0
    opts.frame_opts.snip_edges = True
    opts.mel_opts.num_bins = 80
    f = knf.OnlineFbank(opts)
    f.accept_waveform(float(sr), samples.astype(np.float32))
    f.input_finished()
    return np.array([f.get_frame(i) for i in range(f.num_frames_ready)], dtype=np.float32)


def embedding_onnx(audio: np.ndarray, sr: int = SAMPLE_RATE, *, k: int = 2) -> list[Turn]:
    """VAD区間ごとに CAM++ 埋め込みを作り、コサインKMeans(k) で話者を振る。"""
    import onnxruntime as ort

    model = _model_path()
    if not model.exists():
        raise FileNotFoundError(
            f"話者埋め込みモデルが見つかりません: {model}（python/models/README.md の手順でDL）"
        )
    spans = detect_voiced_spans(audio, sr=sr)
    if len(spans) < k:
        return [Turn(s / sr, e / sr, "spk0") for s, e in spans]

    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    embs = []
    for s, e in spans:
        feats = _fbank(audio[s:e], sr)
        feats = feats - feats.mean(axis=0, keepdims=True)  # 発話内CMN
        emb = sess.run(None, {"x": feats[None].astype(np.float32)})[0][0]
        embs.append(emb)
    x = np.stack(embs)
    x = x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)  # L2正規化＝コサイン空間
    labels = _kmeans(x, k)
    return [Turn(s / sr, e / sr, f"spk{labels[i]}") for i, (s, e) in enumerate(spans)]
