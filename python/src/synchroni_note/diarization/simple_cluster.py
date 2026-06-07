"""簡易クラスタリング話者分離（DD-004 Phase 2, numpy のみ・完全オフライン）。

ロードマップが候補に挙げる「簡易クラスタリング」の最小実装。VAD有声区間ごとに
numpy で音響特徴（対数バンドエネルギー＝音色の粗い指紋）を作り、KMeans(k=2) で2話者に振り分ける。

位置づけ: ONNX話者埋め込み(ECAPA/3D-Speaker)＋クラスタリングの本命手法は外部モデルDL・
onnxruntime 依存が要るため Phase 2 後半（オフライン制約確認後）に回す。本実装は
「依存ゼロで動く実手法」のベースラインで、dummy より実質的に良いかを確認する用途。
既知の制約: 話者数 k は既定で 2 固定（本素材は2話者）。埋め込みでなく素朴な特徴のため精度は限定的。
"""

from __future__ import annotations

import numpy as np

from synchroni_note.bench.vad_segment import detect_voiced_spans
from synchroni_note.diarization.base import SAMPLE_RATE, Turn


def _dct_matrix(n_in: int, n_out: int) -> np.ndarray:
    """DCT-II 行列（log-mel → ケプストラム係数）。"""
    n = np.arange(n_in)
    k = np.arange(n_out)[:, None]
    return np.cos(np.pi / n_in * (n + 0.5) * k)


def _segment_feature(seg: np.ndarray, sr: int, n_bands: int = 26, n_cep: int = 13) -> np.ndarray:
    """有声区間の MFCC 風特徴（話者の声質を捉える低コスト標準特徴）の平均を返す。

    対数バンドエネルギーに DCT を掛けてケプストラム化し、0次（全体エネルギー＝発話内容/音量に依存）
    を捨てて 1..n_cep を使う。生の対数バンドより「誰が話したか」に効きやすい。
    """
    flen = int(0.025 * sr)
    hop = int(0.010 * sr)
    if len(seg) < flen:
        seg = np.pad(seg, (0, flen - len(seg)))
    n = 1 + (len(seg) - flen) // hop
    win = np.hanning(flen)
    frames = np.stack([seg[i * hop : i * hop + flen] * win for i in range(max(1, n))])
    spec = np.abs(np.fft.rfft(frames, axis=1))
    edges = np.linspace(0, spec.shape[1], n_bands + 1).astype(int)
    bands = np.stack([spec[:, edges[i] : edges[i + 1]].sum(1) for i in range(n_bands)], axis=1)
    log_mel = np.log(bands + 1e-6)
    cep = log_mel @ _dct_matrix(n_bands, n_cep).T  # (frames, n_cep)
    return cep[:, 1:].mean(axis=0)  # 0次（全体エネルギー）を捨て、時間平均で声質を要約


def _kmeans(x: np.ndarray, k: int, *, iters: int = 50, restarts: int = 8) -> np.ndarray:
    """numpy 製 KMeans。複数初期値から inertia 最小の割当を返す（決定的シード）。"""
    best_assign, best_inertia = np.zeros(len(x), dtype=int), np.inf
    for r in range(restarts):
        rng = np.random.default_rng(r)  # 決定的（Math.random非依存・再現可能）
        centers = x[rng.choice(len(x), k, replace=False)].copy()
        assign = np.zeros(len(x), dtype=int)
        for _ in range(iters):
            d = ((x[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
            new_assign = d.argmin(1)
            new_centers = np.stack(
                [x[new_assign == j].mean(0) if np.any(new_assign == j) else centers[j]
                 for j in range(k)]
            )
            if np.array_equal(new_assign, assign) and np.allclose(new_centers, centers):
                centers = new_centers
                break
            assign, centers = new_assign, new_centers
        inertia = float(((x - centers[assign]) ** 2).sum())
        if inertia < best_inertia:
            best_inertia, best_assign = inertia, assign
    return best_assign


def simple_cluster(audio: np.ndarray, sr: int = SAMPLE_RATE, *, k: int = 2) -> list[Turn]:
    """VAD区間ごとに音響特徴を作り KMeans(k) で話者ラベルを振る。"""
    spans = detect_voiced_spans(audio, sr=sr)
    if len(spans) < k:
        return [Turn(s / sr, e / sr, "spk0") for s, e in spans]
    feats = np.stack([_segment_feature(audio[s:e], sr) for s, e in spans])
    feats = (feats - feats.mean(0)) / (feats.std(0) + 1e-6)  # z-score
    labels = _kmeans(feats, k)
    return [Turn(s / sr, e / sr, f"spk{labels[i]}") for i, (s, e) in enumerate(spans)]
