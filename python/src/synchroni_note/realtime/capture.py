"""マイク/ファイルから音声を取り込み、無音主体の 8〜12 秒チャンクへ区切る（DD-010 P2-1）。

設計の正: [doc/DD/DD-010/設計_P2収音チャンク化.md]。要点:
- `vad_segment.detect_voiced_spans` は全体配列前提（バッチ）なので、ライブ用に
  **ローリング状態機械 `VadChunker`** を用意する（`frame_rms` は再利用）。
- チャンク確定は「有声 min_speech 秒以上 ＋ 末尾 silence_ms 以上の無音 → 無音の中点でカット」、
  または「蓄積が max_seg 秒に達したら強制カット」（[DD-003] の 8〜12 秒 VAD 区切りを踏襲）。
- `sd.InputStream` のコールバックはブロックを queue へ push するだけ（重い処理を載せない）。

数値は測定で調整できる「つまみ」。既定は DD-003/基本設計の値に合わせる。
"""

from __future__ import annotations

import math
import queue
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from synchroni_note.bench.vad_segment import frame_rms

SAMPLE_RATE = 16000


@dataclass
class Chunk:
    """確定した1チャンク（float32 / 16k / mono）。"""

    seq: int  # 0 始まりの全順序キー（基本設計の seq に相当）
    samples: np.ndarray
    t_start_ms: int  # capture 基点からの相対ms（体感遅延の計測用）
    t_end_ms: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / SAMPLE_RATE


class VadChunker:
    """ローリング VAD でチャンクを切り出す状態機械（I/O を持たない＝pytest 対象）。

    `push(block)` で音声ブロックを足し、確定したチャンク（0個以上）を返す。
    終端で `flush()` を呼ぶと末尾の残りを最終チャンク化する。
    """

    def __init__(
        self,
        *,
        sr: int = SAMPLE_RATE,
        frame_ms: int = 30,
        abs_floor: float = 0.004,
        # DD-010-2 P2: 静かな部屋向け実測で 400→300（自然な無音区切りを最大化）
        silence_ms: int = 300,
        min_speech_s: float = 2.0,
        max_seg_s: float = 10.0,
        search_floor_s: float = 7.0,
        valley_ratio: float = 0.5,
    ) -> None:
        self.sr = sr
        self.frame_len = int(frame_ms * sr / 1000)
        self.abs_floor = abs_floor
        self.silence_frames = max(1, math.ceil(silence_ms / frame_ms))
        self.min_speech_frames = max(1, math.ceil(min_speech_s * 1000 / frame_ms))
        self.max_seg_samples = int(max_seg_s * sr)
        # DD-010-2: 強制カット時に最静点を探す窓 [search_floor, max_seg] と「谷」判定の深さ比。
        self.valley_ratio = valley_ratio
        self.search_floor_samples = min(
            int(search_floor_s * sr), max(0, self.max_seg_samples - self.frame_len)
        )
        self._buf = np.empty(0, dtype=np.float32)
        self._consumed = 0  # これまでに emit 済みのサンプル数（t_start 算出用）
        self._seq = 0

    def push(self, block: np.ndarray) -> list[Chunk]:
        """ブロックを蓄積し、確定したチャンクのリストを返す。"""
        if block.size:
            self._buf = np.concatenate([self._buf, block.astype(np.float32).reshape(-1)])
        out: list[Chunk] = []
        while True:
            cut = self._next_cut()
            if cut is None or cut <= 0:
                break
            out.append(self._emit(cut))
        return out

    def flush(self) -> list[Chunk]:
        """終端処理: 残バッファに有声があれば最終チャンクとして返す。"""
        if self._buf.size and self._has_voice(self._buf):
            return [self._emit(len(self._buf))]
        self._buf = np.empty(0, dtype=np.float32)
        return []

    # --- 内部 ---

    def _flags(self, audio: np.ndarray) -> np.ndarray:
        """30ms フレームごとの有声フラグ（RMS >= abs_floor）。"""
        rms = frame_rms(audio, self.frame_len)
        return rms >= self.abs_floor

    def _has_voice(self, audio: np.ndarray) -> bool:
        flags = self._flags(audio)
        return bool(flags.any())

    def _next_cut(self) -> int | None:
        """現バッファでのカット位置（サンプル index）。無ければ None。"""
        candidates: list[int] = []
        sc = self._silence_cut()
        if sc is not None:
            candidates.append(sc)
        if len(self._buf) >= self.max_seg_samples:
            candidates.append(self._quietest_cut())
        return min(candidates) if candidates else None

    def _silence_cut(self) -> int | None:
        """十分な有声の後にある無音区間の中点（サンプル index）。無ければ None。"""
        flags = self._flags(self._buf)
        n = len(flags)
        voiced_count = 0
        seen_speech = False
        i = 0
        while i < n:
            if flags[i]:
                voiced_count += 1
                if voiced_count >= self.min_speech_frames:
                    seen_speech = True
                i += 1
            else:
                j = i
                while j < n and not flags[j]:
                    j += 1
                run = j - i
                if seen_speech and run >= self.silence_frames:
                    mid_frame = i + run // 2
                    return mid_frame * self.frame_len
                i = j
        return None

    def _quietest_cut(self) -> int:
        """強制カット位置。探索窓 [search_floor, max_seg] 内で最も静かなフレーム境界を返す。

        無音(`_silence_cut`)が取れないまま max_seg に達した時に呼ばれる。10秒ちょうどの機械的な
        カットで単語の途中を割るのを避け、窓内の「音の谷」（息継ぎ・音節の切れ目）で切る。
        谷が十分深くない（ほぼ一様）なら従来どおり max_seg で切る（安全弁, DD-010-2 B2/B3）。
        """
        lo, hi = self.search_floor_samples, self.max_seg_samples
        rms = frame_rms(self._buf[lo:hi], self.frame_len)
        if rms.size == 0:
            return hi
        i_min = int(np.argmin(rms))
        med = float(np.median(rms))
        if med <= 0 or float(rms[i_min]) >= self.valley_ratio * med:
            return hi  # 谷が浅い＝ほぼ一様 → 従来どおり強制カット
        return lo + i_min * self.frame_len + self.frame_len // 2

    def _emit(self, cut: int) -> Chunk:
        samples = self._buf[:cut].copy()
        t_start_ms = int(self._consumed / self.sr * 1000)
        t_end_ms = int((self._consumed + cut) / self.sr * 1000)
        chunk = Chunk(seq=self._seq, samples=samples, t_start_ms=t_start_ms, t_end_ms=t_end_ms)
        self._seq += 1
        self._consumed += cut
        self._buf = self._buf[cut:]
        return chunk


def feed_samples(
    samples: np.ndarray,
    chunker: VadChunker,
    *,
    block_ms: int = 100,
    sink: Callable[[Chunk], None] | None = None,
) -> list[Chunk]:
    """配列音声を mic 代替でブロック分割して chunker に流す（再現測定用）。

    sink を渡すと確定チャンクごとに呼ぶ。常に全チャンクのリストも返す。
    """
    samples = samples.astype(np.float32).reshape(-1)
    block = max(1, int(block_ms * SAMPLE_RATE / 1000))
    out: list[Chunk] = []
    for start in range(0, len(samples), block):
        for ch in chunker.push(samples[start : start + block]):
            out.append(ch)
            if sink:
                sink(ch)
    for ch in chunker.flush():
        out.append(ch)
        if sink:
            sink(ch)
    return out


def capture_mic(
    chunker: VadChunker,
    sink: Callable[[Chunk], None],
    *,
    device: int | None = None,
    block_ms: int = 100,
    stop_event: threading.Event | None = None,
    paused: threading.Event | None = None,
) -> None:
    """マイクからライブ収音し、確定チャンクを sink に渡す（16k/mono/f32）。

    コールバックは「キューへ push するだけ」。VAD/STT は本ループ側で行う。
    `stop_event` がセットされると flush して終了。`paused` がセットされている間は
    ブロックを破棄する（＝チャンカに入れない＝時間も進めない＝一時停止）。

    診断メッセージは **stderr** へ出す（呼び出し側が stdout を JSON 専用に使うため汚さない）。
    """
    import sounddevice as sd

    q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, _frames, _time, status) -> None:  # noqa: ANN001 (sd 既定シグネチャ)
        if status:
            print(f"[capture] {status}", file=sys.stderr, flush=True)
        q.put(indata[:, 0].copy())

    blocksize = max(1, int(block_ms * SAMPLE_RATE / 1000))
    stop_event = stop_event or threading.Event()
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        device=device,
        callback=_cb,
    ):
        print("● 録音中 ... Ctrl+C で終了", file=sys.stderr, flush=True)
        while not stop_event.is_set():
            try:
                block = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if paused is not None and paused.is_set():
                continue  # 一時停止中は破棄（チャンカに入れない）
            for ch in chunker.push(block):
                sink(ch)
        for ch in chunker.flush():
            sink(ch)
