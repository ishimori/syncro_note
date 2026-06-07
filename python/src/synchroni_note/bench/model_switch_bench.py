"""ライブ整形モデル(qwen3:8b) → 終了後バッチ清書モデル(gemma4:26b) の
モデル切替シーケンスを実測する（DD-006）。

切替方式（基本設計書 §4.3）: keep_alive=0 で退避 → ollama.ps() 空確認 → 特大MoEロード。
スクリプト側で順序を保証し、(1) 二重常駐窓が出ないこと (2) 切替秒数の内訳・RSS推移
(3) 清書実時間 を計測する。清書 tok/s から §6 想定の出力規模を外挿し UI文言を出す。

RSS/ps は別スレッドで連続サンプリングするため、26b ロード中・清書生成中のピークも捕捉する。

使い方（python/ 配下。Ollama 起動とモデル pull が前提）:
    uv run python -m synchroni_note.bench.model_switch_bench
    uv run python -m synchroni_note.bench.model_switch_bench --runs 2 --out ../doc/DD/DD-006/結果.md
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import ollama
import psutil

from synchroni_note.bench.llm_bench import run_once
from synchroni_note.pipeline.summarize import build_minutes_prompt

LIVE_MODEL = "qwen3:8b"
BATCH_MODEL = "gemma4:26b"
POLL_S = 0.2  # 退避（8b消失）待ちのポーリング間隔
SAMPLE_S = 0.3  # RSS/ps 連続サンプリング間隔
UNLOAD_TIMEOUT_S = 30.0
LIVE_WARMUP_PROMPT = "次の発話を整形: えーっと、本日はよろしくお願いします。"
# 基本設計書 §6 想定の清書出力規模（UI文言「清書中…約N分」の外挿に使う）
EXTRAPOLATION_TOKENS: tuple[int, ...] = (1000, 2000, 4000)


@dataclass
class PsSnapshot:
    """ある時点の ollama.ps() とプロセスRSSのスナップショット。"""

    t_s: float  # サイクル基点からの経過秒
    names: list[str]  # ロード中モデル名
    rss_gb: float  # ollama 系プロセス合算RSS


@dataclass
class SwitchResult:
    """1サイクルの切替計測結果。"""

    cold: bool
    switch_total_s: float  # 退避要求 → batch TTFT（UIの体感切替待ち）
    unload_wait_s: float  # 退避要求 → 8b が ps から消える
    batch_load_ttft_s: float  # 8b消失（=26bロード開始）→ 26b 最初のトークン
    cleanup_s: float  # 26b TTFT → 清書完了（清書本体）
    clean_tps: float  # 清書 生成tok/s
    output_tokens: int
    double_resident: bool  # 8b と 26b が同時に載った瞬間があったか
    rss_peak_gb: float
    timeline: list[PsSnapshot] = field(default_factory=list)


def loaded_model_names() -> list[str]:
    """現在 Ollama にロードされているモデル名一覧（取得失敗時は空）。"""
    try:
        resp = ollama.ps()
    except Exception:
        return []
    names: list[str] = []
    for m in resp.models:
        name = getattr(m, "model", None) or getattr(m, "name", None)
        if name:
            names.append(name)
    return names


def ollama_rss_gb() -> float:
    """ollama 関連プロセス（server ＋ runner 子）の RSS 合計を GB で返す。

    runner 子プロセスがモデル本体のメモリを持つため children を辿って合算する。
    process_iter と children の二重計上を PID で排除する。
    """
    seen: set[int] = set()
    total = 0
    for proc in psutil.process_iter(["name"]):
        if "ollama" not in (proc.info.get("name") or "").lower():
            continue
        try:
            group = [proc, *proc.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for p in group:
            if p.pid in seen:
                continue
            seen.add(p.pid)
            try:
                total += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return total / 1e9


def detect_double_resident(timeline: Sequence[PsSnapshot], a: str, b: str) -> bool:
    """timeline 中に a と b が同時にロードされた瞬間があるか（純関数）。"""
    return any(a in s.names and b in s.names for s in timeline)


def extrapolate_cleanup(
    tps: float, output_tokens: Sequence[int] = EXTRAPOLATION_TOKENS
) -> list[tuple[int, float]]:
    """清書 tok/s から出力規模別の所要秒を外挿する（純関数・0除算ガード）。"""
    return [(n, (n / tps) if tps > 0 else 0.0) for n in output_tokens]


def _unload(model: str) -> None:
    """model に keep_alive=0 を投げて退避要求する（空生成）。"""
    try:
        ollama.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def _wait_gone(target: str, t_req: float) -> float:
    """target が ps から消えるまで（or タイムアウト）待ち、t_req からの経過秒を返す。"""
    deadline = t_req + UNLOAD_TIMEOUT_S
    while target in loaded_model_names() and time.perf_counter() < deadline:
        time.sleep(POLL_S)
    return time.perf_counter() - t_req


def run_switch_cycle(transcript: str, *, cold: bool) -> SwitchResult:
    """1サイクル実測: live(8b)常駐 → 退避 → ps空待ち → batch(26b)清書。

    別スレッドで RSS/ps を SAMPLE_S 間隔で連続サンプリングするため、26b ロード中・
    清書生成中の RSS ピークと二重常駐窓を取りこぼさない。
    """
    timeline: list[PsSnapshot] = []
    t_origin = time.perf_counter()
    rss_peak = 0.0
    stop = threading.Event()

    def sampler() -> None:
        nonlocal rss_peak
        while not stop.is_set():
            rss = ollama_rss_gb()
            rss_peak = max(rss_peak, rss)
            timeline.append(PsSnapshot(time.perf_counter() - t_origin, loaded_model_names(), rss))
            stop.wait(SAMPLE_S)

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()
    try:
        # 1. live ロード（warmup・常駐）
        run_once(LIVE_MODEL, LIVE_WARMUP_PROMPT, keep_alive=-1)
        # 2. 退避要求 → 3. ps 空待ち（8b 消失）
        t_req = time.perf_counter()
        _unload(LIVE_MODEL)
        unload_wait_s = _wait_gone(LIVE_MODEL, t_req)
        # 4. batch(26b) ロード＋清書（run_once の TTFT に 26b コールドロードが含まれる）
        batch = run_once(BATCH_MODEL, build_minutes_prompt(transcript), keep_alive=-1)
    finally:
        stop.set()
        sampler_thread.join(timeout=2.0)

    rss_peak = max(rss_peak, ollama_rss_gb())
    return SwitchResult(
        cold=cold,
        switch_total_s=unload_wait_s + batch.ttft_s,
        unload_wait_s=unload_wait_s,
        batch_load_ttft_s=batch.ttft_s,
        cleanup_s=batch.total_s - batch.ttft_s,
        clean_tps=batch.gen_tps,
        output_tokens=batch.eval_count,
        double_resident=detect_double_resident(timeline, LIVE_MODEL, BATCH_MODEL),
        rss_peak_gb=rss_peak,
        timeline=timeline,
    )


def format_markdown(results: list[SwitchResult]) -> str:
    """計測結果を Markdown に整形する（切替表＋UI文言の外挿表）。"""
    lines = [
        "# DD-006 モデル切替シーケンス実測結果",
        "",
        f"- live={LIVE_MODEL} / batch={BATCH_MODEL} / poll={POLL_S}s / sample={SAMPLE_S}s",
        "- 切替方式: keep_alive=0 退避 → ollama.ps() 空確認 → 26bロード（基本設計書 §4.3）",
        "",
        "| run | 種別 | 切替合計(s) | unload待ち(s) | 26bロード+TTFT(s) | 清書本体(s) "
        "| 清書tok/s | 出力tok | 二重常駐 | RSSピーク(GB) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {'cold' if r.cold else 'warm'} | {r.switch_total_s:.2f} "
            f"| {r.unload_wait_s:.2f} | {r.batch_load_ttft_s:.2f} | {r.cleanup_s:.2f} "
            f"| {r.clean_tps:.1f} | {r.output_tokens} "
            f"| {'⚠️あり' if r.double_resident else 'なし'} | {r.rss_peak_gb:.2f} |"
        )
    tpss = [r.clean_tps for r in results if r.clean_tps > 0]
    if tpss:
        tps = sum(tpss) / len(tpss)
        lines += [
            "",
            f"## 清書所要の外挿（清書 {tps:.1f} tok/s で §6 出力規模を換算）",
            "",
            "| 出力tok | 清書所要 |",
            "|---|---|",
        ]
        for n, sec in extrapolate_cleanup(tps):
            lines.append(f"| {n} | 約 {sec / 60:.1f} 分（{sec:.0f}秒） |")
    any_double = any(r.double_resident for r in results)
    peak = max((r.rss_peak_gb for r in results), default=0.0)
    lines += [
        "",
        "## 合否ゲート（§9）",
        "",
        f"- 二重常駐窓: {'⚠️ 検出あり（NG）' if any_double else 'なし（OK）'}",
        f"- RSSピーク: {peak:.2f} GB（低RAM=9.6GB 環境での搭載可否の判定材料）",
    ]
    return "\n".join(lines) + "\n"


def _default_transcript_path() -> Path:
    return Path(__file__).parent / "sample_transcript.txt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ollama モデル切替シーケンス実測（DD-006）")
    parser.add_argument("--runs", type=int, default=2, help="計測サイクル数（1本目=cold）")
    parser.add_argument("--transcript", type=Path, default=None, help="清書入力テキスト")
    parser.add_argument("--out", type=Path, default=None, help="結果Markdownの出力先")
    args = parser.parse_args(argv)

    transcript = (args.transcript or _default_transcript_path()).read_text(encoding="utf-8")

    pre = loaded_model_names()
    if pre:
        print(f"[警告] 開始時にロード済みモデルあり: {pre}（別プロセスのOllama利用と競合の可能性）")

    results: list[SwitchResult] = []
    for i in range(args.runs):
        cold = i == 0
        print(f"[サイクル {i + 1}/{args.runs}] cold={cold} ...")
        r = run_switch_cycle(transcript, cold=cold)
        results.append(r)
        print(
            f"  -> 切替 {r.switch_total_s:.2f}s "
            f"(unload {r.unload_wait_s:.2f}s + load/TTFT {r.batch_load_ttft_s:.2f}s) "
            f"| 清書 {r.cleanup_s:.2f}s @ {r.clean_tps:.1f}tok/s "
            f"| 二重常駐={'あり' if r.double_resident else 'なし'} "
            f"| RSSピーク {r.rss_peak_gb:.2f}GB"
        )
        # 次サイクルのためクリーンに戻す（26b を退避し ps 空を待つ）
        _unload(BATCH_MODEL)
        _wait_gone(BATCH_MODEL, time.perf_counter())

    md = format_markdown(results)
    print()
    print(md)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"結果を書き出しました: {args.out}")

    any_double = any(r.double_resident for r in results)
    print(f"\n[合否] 二重常駐窓: {'⚠️ 検出あり（NG）' if any_double else 'なし（OK）'}")
    return 1 if any_double else 0


if __name__ == "__main__":
    raise SystemExit(main())
