"""話者分離ベンチ CLI（DD-004 Phase 1）。

参照RTTM(無ければ自動生成) を正解に、各 diarize 手法の DER / 話者数 / RTF を表で出す。
使い方:
    uv run python -m synchroni_note.bench.diarization_bench \
        --audio audio/sample02.wav --turns audio/script02_turns.json --method all

`--build-ref` か参照RTTM不在時は、正解ターン(JSON)から forced alignment で RTTM を生成・保存する。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from synchroni_note.diarization.base import METHODS, SAMPLE_RATE, load_wav_mono16k
from synchroni_note.diarization.reference import build_reference_turns
from synchroni_note.diarization.rttm import der, read_rttm, write_rttm


def main() -> None:
    p = argparse.ArgumentParser(description="DD-004 話者分離ベンチ")
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--ref", type=Path, default=None, help="参照RTTM（既定: 音声と同名 .rttm）")
    p.add_argument(
        "--turns", type=Path, default=None, help="正解ターンJSON（既定: 音声stem_turns.json）"
    )
    p.add_argument("--method", default="all", help="手法名 or all（既定: all）")
    p.add_argument("--speakers", type=int, default=2, help="想定話者数 k（既定: 2。sample03は4）")
    p.add_argument("--model", default="medium", help="参照生成のwhisperモデル")
    p.add_argument("--collar", type=float, default=0.25)
    p.add_argument("--build-ref", action="store_true", help="参照RTTMを強制再生成")
    args = p.parse_args()

    audio_path: Path = args.audio
    ref_path: Path = args.ref or audio_path.with_suffix(".rttm")
    turns_path: Path = args.turns or audio_path.with_name(audio_path.stem + "_turns.json")

    audio = load_wav_mono16k(audio_path)
    dur_s = len(audio) / SAMPLE_RATE

    if args.build_ref or not ref_path.exists():
        print(f"[ref] forced alignment で参照RTTMを生成中: {turns_path} -> {ref_path}")
        ref_turns = build_reference_turns(audio_path, turns_path, model_size=args.model)
        write_rttm(ref_path, audio_path.stem, ref_turns)
        print(f"[ref] {len(ref_turns)} ターンを書き出しました")

    ref = read_rttm(ref_path)
    methods = list(METHODS) if args.method == "all" else [args.method]

    print(
        f"\naudio={audio_path.name}  dur={dur_s:.1f}s  k={args.speakers}  "
        f"collar={args.collar}s  ref_turns={len(ref)}"
    )
    print(f"{'method':<10}{'DER':>7}{'miss':>7}{'FA':>7}{'conf':>7}{'spk_ref':>8}{'spk_hyp':>8}{'RTF':>7}")
    for name in methods:
        fn = METHODS[name]
        t0 = time.perf_counter()
        hyp = fn(audio, SAMPLE_RATE, args.speakers)
        rtf = (time.perf_counter() - t0) / dur_s
        r = der(ref, hyp, collar=args.collar).as_row()
        print(
            f"{name:<10}{r['DER']:>7}{r['miss']:>7}{r['FA']:>7}{r['conf']:>7}"
            f"{r['spk_ref']:>8}{r['spk_hyp']:>8}{rtf:>7.3f}"
        )


if __name__ == "__main__":
    main()
