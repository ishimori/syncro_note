"""会議後の一括話者ラベリング（DD-012-5）。

文字起こしセグメント（テキスト＋開始/終了ms）に「話者ラベル(spk0/spk1/…)」を後付けする。
話者分離アルゴリズム自体は DD-004 系列の成果（``diarization`` 配下の各手法）をそのまま使い、
本モジュールは **「どの手法を使うか（差し替え口）」と「Turn→セグメントへの対応付け」** だけを担う。

DD-004-1（本採用手法の評価・確定）は別セッションで進行中だが、手法の *実体* は既に動く
（``onnx-embed`` = CAM++ ONNX 埋め込み。やさしい音声で検証済み）。よって採用確定を待たずに、
本モジュール経由で先行配線できる。DD-004-1 が確定したら ``DEFAULT_METHOD`` を1か所
差し替えるだけで本採用版へ載せ替わる（＝唯一の差し替え口）。

付与タイミングは基本設計が推奨する **会議後（終了後）一括**。ライブ逐次（録音しながらの
オンライン話者割当）は精度/速度の作り込みが要るため、DD-004-1 の結論待ちとして
本モジュールでは扱わない。
"""

from __future__ import annotations

import sys

import numpy as np

from synchroni_note.diarization.base import METHODS, SAMPLE_RATE, Turn

# 唯一の差し替え口: 本採用手法。DD-004-1 確定後はここを変えるだけで全経路が載せ替わる。
DEFAULT_METHOD = "onnx-embed"
# モデル未配置/実行失敗時の保険（純numpy・完全オフライン・無モデル）。
_FALLBACK_METHOD = "simple-cluster"
# 想定話者数 k。話者数の自動推定は DD-004-1 で後回し中のため暫定の既定値（呼び側で上書き可）。
DEFAULT_SPEAKERS = 2


def diarize_for_labeling(
    audio: np.ndarray,
    sr: int = SAMPLE_RATE,
    *,
    k: int = DEFAULT_SPEAKERS,
    method: str = DEFAULT_METHOD,
) -> list[Turn]:
    """音声全体を一度だけ話者分離し、話者区間（Turn 列）を返す。

    本採用手法 → フォールバック（無モデル）の順に試す。どれも失敗したら空リストを返し、
    呼び側は全セグメントを単一話者として扱う（＝文字起こし自体は決して止めない方針）。
    どの手法が使われたか・失敗理由は stderr に出す（stdout は JSON 専用に保つ）。
    """
    for name in dict.fromkeys([method, _FALLBACK_METHOD]):  # 重複除去・順序維持
        fn = METHODS.get(name)
        if fn is None:
            continue
        try:
            turns = fn(audio, sr, k)
            print(f"[diarize] method={name} k={k} turns={len(turns)}", file=sys.stderr, flush=True)
            return turns
        except Exception as e:  # noqa: BLE001  モデル未DL/実行失敗でも止めず次の手法へ
            print(f"[diarize] {name} failed: {e!r}; フォールバックへ", file=sys.stderr, flush=True)
    return []


def speaker_for_span(turns: list[Turn], t_start_ms: int, t_end_ms: int) -> str:
    """1セグメント [t_start_ms, t_end_ms) に最も長く重なる話者ラベルを返す。

    複数 Turn にまたがる場合は話者ごとに重なり長を合計し、最大の話者を採用する。
    どの Turn とも重ならなければ ``"spk0"``（無分離時の既定）。
    """
    overlap: dict[str, float] = {}
    for t in turns:
        on_ms = t.onset_s * 1000.0
        off_ms = t.offset_s * 1000.0
        dur = min(t_end_ms, off_ms) - max(t_start_ms, on_ms)
        if dur > 0:
            overlap[t.speaker] = overlap.get(t.speaker, 0.0) + dur
    if not overlap:
        return "spk0"
    return max(overlap, key=lambda s: overlap[s])


def assign_speakers(turns: list[Turn], spans_ms: list[tuple[int, int]]) -> list[str]:
    """セグメント時間範囲の列に話者ラベルを一括で振る（``speaker_for_span`` の束ね）。"""
    return [speaker_for_span(turns, s, e) for s, e in spans_ms]


def _next_free_label(reserved: set[str]) -> str:
    """``reserved`` に無い最小の ``spk{n}`` を返す（新規話者への採番）。"""
    i = 0
    while f"spk{i}" in reserved:
        i += 1
    return f"spk{i}"


def stabilize_labels(prev_map: dict[str, str], new_map: dict[str, str]) -> dict[str, str]:
    """今回の生ラベルマップ(``new_map``)を前回マップ(``prev_map``)と整合するよう relabel する。

    ローリング再分離（DD-017-2）では回ごとにクラスタ順が変わり spk0↔spk1 が入れ替わって
    画面の色がチラつく。これを防ぐため、共有 seq 上で一致が最大になるラベル置換を貪欲に
    決め、前回ラベルへ寄せる。前回に無い新規話者には未使用の spk 番号を割り当てる。
    ``prev_map`` が空（初回）なら ``new_map`` をそのまま返す。純関数（副作用なし・決定的）。

    引数・戻り値の map はいずれも ``{seq(str): "spk{n}"}``。
    """
    if not prev_map:
        return dict(new_map)
    # 共有 seq での (新ラベル, 旧ラベル) 一致数を集計
    shared = new_map.keys() & prev_map.keys()
    counts: dict[tuple[str, str], int] = {}
    for seq in shared:
        key = (new_map[seq], prev_map[seq])
        counts[key] = counts.get(key, 0) + 1
    # 一致数の多い順に 1対1 で割当（貪欲マッチ）。同数はラベル名で決定的に解決。
    remap: dict[str, str] = {}
    used_targets: set[str] = set()
    for new_lbl, old_lbl in sorted(counts, key=lambda p: (-counts[p], p[0], p[1])):
        if new_lbl in remap or old_lbl in used_targets:
            continue
        remap[new_lbl] = old_lbl
        used_targets.add(old_lbl)
    # 未割当の新ラベル（＝新規話者）に未使用 spk 番号を採番（既存の色を避ける）
    reserved = set(prev_map.values()) | used_targets
    for new_lbl in dict.fromkeys(new_map.values()):  # 出現順・重複除去で決定的
        if new_lbl in remap:
            continue
        remap[new_lbl] = _next_free_label(reserved)
        reserved.add(remap[new_lbl])
    return {seq: remap[lbl] for seq, lbl in new_map.items()}
