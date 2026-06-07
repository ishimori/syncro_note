"""RTTM 入出力と DER(Diarization Error Rate) 計測（DD-004 Phase 1, 自前実装）。

DER は話者分離評価の標準指標で、(miss + false_alarm + speaker_confusion) / 参照発話時間。
外部依存(pyannote.metrics 等)を増やさず numpy だけで実装する（完全オフライン要件と依存最小のため）。
- collar: 参照の話者交代境界の前後 ±collar/2 を採点除外（境界の時刻誤差を吸収）。標準 0.25s。
- 話者ラベルの最適対応付け: 推定ラベルと正解ラベルの対応は未知なので、重なりが最大になる
  injective 対応を総当たり（話者数<=4 を想定）で選び、confusion を最小化する。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from pathlib import Path

import numpy as np

from synchroni_note.diarization.base import Turn


def write_rttm(path: Path, uri: str, turns: list[Turn]) -> None:
    """Turn 列を NIST RTTM 形式で書き出す。"""
    lines = [
        f"SPEAKER {uri} 1 {t.onset_s:.3f} {t.duration_s:.3f} <NA> <NA> {t.speaker} <NA> <NA>"
        for t in turns
        if t.duration_s > 0
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_rttm(path: Path) -> list[Turn]:
    """RTTM ファイルを Turn 列に読み込む（SPEAKER 行のみ解釈）。"""
    turns: list[Turn] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or parts[0] != "SPEAKER":
            continue
        onset, dur = float(parts[3]), float(parts[4])
        speaker = parts[7]
        turns.append(Turn(onset_s=onset, offset_s=onset + dur, speaker=speaker))
    return turns


def _labelize(turns: list[Turn], n_frames: int, resolution: float) -> tuple[np.ndarray, list[str]]:
    """Turn 列を frame ごとの話者ラベル index 配列に変換（無音= -1）。"""
    labels = sorted({t.speaker for t in turns})
    idx = {name: i for i, name in enumerate(labels)}
    frame = np.full(n_frames, -1, dtype=np.int64)
    for t in turns:
        s = int(round(t.onset_s / resolution))
        e = int(round(t.offset_s / resolution))
        frame[max(0, s) : min(n_frames, e)] = idx[t.speaker]
    return frame, labels


@dataclass
class DERResult:
    der: float
    miss: float
    false_alarm: float
    confusion: float
    ref_total_s: float
    n_ref_speakers: int
    n_hyp_speakers: int

    def as_row(self) -> dict[str, float | int]:
        return {
            "DER": round(self.der, 4),
            "miss": round(self.miss, 4),
            "FA": round(self.false_alarm, 4),
            "conf": round(self.confusion, 4),
            "spk_ref": self.n_ref_speakers,
            "spk_hyp": self.n_hyp_speakers,
        }


def der(
    ref: list[Turn],
    hyp: list[Turn],
    *,
    collar: float = 0.25,
    resolution: float = 0.01,
) -> DERResult:
    """参照(ref)と推定(hyp)の DER を計算する（frameベース）。

    DER = (miss + false_alarm + confusion) / 参照発話時間（いずれも採点対象frameのみ）。
    confusion は話者ラベルの最適対応付け後の不一致。比率は秒ではなく参照発話時間で正規化。
    """
    duration = max(
        [t.offset_s for t in ref] + [t.offset_s for t in hyp] + [0.0]
    )
    n = int(np.ceil(duration / resolution)) + 1
    ref_frame, ref_labels = _labelize(ref, n, resolution)
    hyp_frame, hyp_labels = _labelize(hyp, n, resolution)

    # collar: 参照の各境界(onset/offset)の前後 ±collar/2 を採点除外
    scored = np.ones(n, dtype=bool)
    half = int(round((collar / 2) / resolution))
    if half > 0:
        for t in ref:
            for b in (t.onset_s, t.offset_s):
                c = int(round(b / resolution))
                scored[max(0, c - half) : min(n, c + half + 1)] = False

    ref_present = (ref_frame >= 0) & scored
    hyp_present = (hyp_frame >= 0) & scored

    miss = int(np.sum(ref_present & ~hyp_present))
    false_alarm = int(np.sum(hyp_present & ~ref_present))
    both = ref_present & hyp_present

    # 話者ラベル最適対応付け（重なり最大化＝confusion最小化）を総当たり
    overlap = np.zeros((len(hyp_labels), len(ref_labels)), dtype=np.int64)
    rb, hb = ref_frame[both], hyp_frame[both]
    for h, r in zip(hb, rb):
        overlap[h, r] += 1
    best_match = 0
    n_h, n_r = len(hyp_labels), len(ref_labels)
    if n_h and n_r:
        if n_h <= n_r:
            for perm in permutations(range(n_r), n_h):
                best_match = max(best_match, int(sum(overlap[h, perm[h]] for h in range(n_h))))
        else:
            for perm in permutations(range(n_h), n_r):
                best_match = max(best_match, int(sum(overlap[perm[r], r] for r in range(n_r))))
    confusion = int(np.sum(both)) - best_match

    ref_total = int(np.sum(ref_present))
    res = resolution
    if ref_total == 0:
        return DERResult(0.0, 0.0, 0.0, 0.0, 0.0, len(ref_labels), len(hyp_labels))
    return DERResult(
        der=(miss + false_alarm + confusion) / ref_total,
        miss=miss / ref_total,
        false_alarm=false_alarm / ref_total,
        confusion=confusion / ref_total,
        ref_total_s=ref_total * res,
        n_ref_speakers=len(ref_labels),
        n_hyp_speakers=len(hyp_labels),
    )
