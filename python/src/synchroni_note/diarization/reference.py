"""正解ターン(話者ラベル付き) + whisper word timestamps から参照RTTMを生成する（DD-004 Phase 1）。

sample02 は「鈴木↔佐藤が交互・順序確定・無オーバーラップ」で音読された素材なので、
正解テキスト(ターン区切り)を音声に forced alignment すれば、手作業アノテーションなしで
話者区間(RTTM)を導出できる。手順:

1. faster-whisper を word_timestamps=True で実行 → 全単語列 [(text, start_s, end_s)]。
2. 正規化(句読点/空白除去)した whisper連結文字列と 正解ターン連結文字列 を
   difflib で文字対応付け。
3. 正解側のターン境界の文字位置を whisper 側へ写像 → その位置の単語の前後の
   無音ギャップ中点を境界時刻とする。
4. 各ターンに話者ラベルを付けて Turn 列(=参照RTTM)を構成する。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from synchroni_note.bench.vad_segment import detect_voiced_spans
from synchroni_note.diarization.base import SAMPLE_RATE, Turn, load_wav_mono16k

_PUNCT = re.compile(r"[\s、。．，！？「」『』（）()・〜ー…,.!?]+")


def intersect_with_voiced(turns: list[Turn], voiced_s: list[tuple[float, float]]) -> list[Turn]:
    """各ターンを有声区間と交差させ、無音部分を発話から除く（純関数）。

    参照を「最初の語〜最後の語まで連続発話」で作ると、ターン内/間のポーズまで発話扱いになり、
    VADベース手法が無音を miss として水増し計上してしまう。有声区間と交差させて実発話だけ残す。
    """
    out: list[Turn] = []
    for t in turns:
        for vs, ve in voiced_s:
            s, e = max(t.onset_s, vs), min(t.offset_s, ve)
            if e > s:
                out.append(Turn(onset_s=s, offset_s=e, speaker=t.speaker))
    return out


def normalize(text: str) -> str:
    """対応付け用に正規化（NFKC・句読点/空白除去）。文字単位アラインのため空白も全除去。"""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class Word:
    text: str
    start_s: float
    end_s: float


def transcribe_words(
    audio_path: Path, *, model_size: str = "medium", threads: int = 8
) -> list[Word]:
    """faster-whisper で単語単位タイムスタンプ付きの文字起こしを行う。"""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=threads)
    segments, _info = model.transcribe(
        str(audio_path),
        language="ja",
        beam_size=1,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            words.append(Word(text=w.word, start_s=float(w.start), end_s=float(w.end)))
    return words


def _map_ref_to_hyp(ref: str, hyp: str) -> list[int]:
    """ref の各文字位置に対応する hyp 文字位置を返す（difflib のマッチブロック＋前方補完）。"""
    mapping: list[int | None] = [None] * len(ref)
    sm = SequenceMatcher(None, ref, hyp, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            mapping[a + k] = b + k
    # 未対応位置を前後の確定値で補完（単調性を保つ）
    last = 0
    for i in range(len(ref)):
        if mapping[i] is None:
            mapping[i] = last
        else:
            last = mapping[i]
    return [m for m in mapping]  # type: ignore[misc]


def build_reference_turns(
    audio_path: Path, turns_json: Path, *, model_size: str = "medium", vad_intersect: bool = True
) -> list[Turn]:
    """正解ターン(JSON)と音声から参照 Turn 列を生成する。

    vad_intersect=True で有声区間と交差させ、無音を発話から除く（miss 水増し対策, DD-004 Phase 2）。
    """
    spec = json.loads(Path(turns_json).read_text(encoding="utf-8"))
    raw_turns = spec["turns"]
    words = transcribe_words(audio_path, model_size=model_size)
    if not words:
        raise RuntimeError("whisper が単語を返さなかった（音声/モデルを確認）")

    # hyp 文字列と「各文字 -> 単語index」対応
    hyp_chars: list[str] = []
    char_to_word: list[int] = []
    for wi, w in enumerate(words):
        for ch in normalize(w.text):
            hyp_chars.append(ch)
            char_to_word.append(wi)
    hyp = "".join(hyp_chars)

    # ref 文字列と「各ターンの終了文字位置(累積)」
    norm_turns = [normalize(t["text"]) for t in raw_turns]
    ref = "".join(norm_turns)
    ref_to_hyp = _map_ref_to_hyp(ref, hyp)

    def boundary_time(ref_char_offset: int) -> float:
        """ref の文字境界 → hyp 文字 → 単語 → 無音ギャップ中点の時刻。"""
        if ref_char_offset <= 0:
            return words[0].start_s
        hyp_pos = min(ref_to_hyp[min(ref_char_offset, len(ref) - 1)], len(char_to_word) - 1)
        wi = char_to_word[hyp_pos]
        prev_end = words[wi - 1].end_s if wi > 0 else words[wi].start_s
        return (prev_end + words[wi].start_s) / 2.0

    # 各ターンの累積終了オフセット（最後のターンは音声末尾）
    boundaries: list[float] = []
    acc = 0
    for nt in norm_turns[:-1]:
        acc += len(nt)
        boundaries.append(boundary_time(acc))
    # 単調増加に補正
    for i in range(1, len(boundaries)):
        boundaries[i] = max(boundaries[i], boundaries[i - 1])

    turns: list[Turn] = []
    starts = [words[0].start_s] + boundaries
    ends = boundaries + [words[-1].end_s]
    for spec_turn, onset, offset in zip(raw_turns, starts, ends):
        if offset > onset:
            turns.append(Turn(onset_s=onset, offset_s=offset, speaker=spec_turn["speaker"]))

    if vad_intersect:
        audio = load_wav_mono16k(audio_path)
        voiced_s = [(s / SAMPLE_RATE, e / SAMPLE_RATE) for s, e in detect_voiced_spans(audio)]
        turns = intersect_with_voiced(turns, voiced_s)
    return turns
