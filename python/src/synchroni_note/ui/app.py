"""SynchroniNote 評価期UI（gradio）: ブラウザで音声→議事録Markdown。

起動:
    uv run synchroni-note-ui
    # ブラウザで http://127.0.0.1:7860 を開く

マイク録音 or 音声ファイルを入れて「議事録を作成」を押すと、議事録が表示される。
処理中は音声長・経過時間（リアルタイム）・出力トークン数を表示し、完了時に合計時間と
入出力トークン数・生成速度を出す。完全ローカル（クラウド送信なし）。本番UIは Quasar/Tauri（別途）。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

from synchroni_note.pipeline.cleaning import clean_text
from synchroni_note.pipeline.cli import DEMO_VOCAB
from synchroni_note.pipeline.summarize import stream_summarize
from synchroni_note.pipeline.transcribe import stream_transcribe

# (表示ラベル, 実際のモデルID)。ラベルで規模感・用途が分かるようにする。
SUMMARY_MODELS = [
    ("gemma4:26b — 高品質・本機最速（おすすめ）", "gemma4:26b"),
    ("qwen3:8b — 中品質・標準", "qwen3:8b"),
    ("gemma4:e4b — 軽量・最速・品質は控えめ", "gemma4:e4b"),
]
STT_MODELS = [
    ("medium — 高精度・日本語向き（おすすめ）", "medium"),
    ("small — 中間（速さ寄り）", "small"),
    ("base — 高速だが精度は低め", "base"),
]

MODEL_HELP = """### 🧭 モデルの選び方（迷ったら既定のままでOK）

**「b」= パラメータ数（モデルの規模）。** 大きいほど賢い反面、重く（遅く・メモリ大）なります。

**要約モデル**（書き起こしから議事録の文章を作る）

| 選択肢 | 規模 | 議事録の品質 | 速度 | 使いどころ |
|---|---|---|---|---|
| **gemma4:26b**（既定） | 大（260億/MoE） | ◎ 最高 | ◎ 速い | **おすすめ**。大きい割に速い |
| qwen3:8b | 中（80億） | ○ 良い | △ やや遅い | 26bが使えない時の代替 |
| gemma4:e4b | 小（軽量） | △ ふつう | ◎ 最速 | メモリ節約・とにかく速く |

→ 本機の実測では **gemma4:26b が品質・速度とも一番**でした。基本これでOK。

**文字起こしモデル**（音声 → テキスト）

| 選択肢 | 日本語の精度 | 速度 | 使いどころ |
|---|---|---|---|
| **medium**（既定） | ◎ 高い | △ やや重い | **おすすめ**。実用精度 |
| small | ○ 中くらい | ○ 速い | 速さ優先でそこそこ |
| base | △ 低い | ◎ 最速 | 下書き・最速重視（誤りは増える） |

→ 日本語は **medium** で精度が大きく上がります（base は固有名詞の誤りが増加）。迷ったら medium。
"""


def make_minutes(
    audio_path: str | None,
    title: str,
    agenda: str,
    summary_model: str,
    stt_model: str,
) -> Iterator[tuple[str, str, str]]:
    """音声→議事録を生成し、(情報行, 議事録Markdown, 書き起こし) を逐次返す。

    情報行に 音声長・経過時間（リアルタイム）・トークン数 を表示する。
    """
    if not audio_path:
        yield "⚠️ 先に音声を録音するか、ファイルを入れてください。", "", ""
        return

    t0 = time.perf_counter()
    yield "⏳ 準備中（モデル読み込み）…", "⏳ 文字起こしを開始します…", ""

    stream = stream_transcribe(Path(audio_path), model_size=stt_model)
    dur = stream.duration_s

    def info(phase: str) -> str:
        elapsed = time.perf_counter() - t0
        return f"🎧 音声長 **{dur:.1f}秒** ｜ ⏱ 経過 **{elapsed:.1f}秒** ｜ {phase}"

    segs: list = []
    yield info(f"文字起こし中（{stt_model} + VAD）…"), "⏳ 文字起こし中…", ""
    for seg in stream.segments:
        segs.append(seg)
        raw = "".join(s.text for s in segs)
        phase = f"文字起こし中（{stt_model} + VAD）— {len(segs)}セグメント"
        yield info(phase), "⏳ 文字起こし中…", raw

    raw = "".join(s.text for s in segs)
    cleaned = clean_text(raw, vocab=DEMO_VOCAB)
    stt_s = time.perf_counter() - t0

    header = f"# {title}\n\n" if title else ""
    terms = sorted(set(DEMO_VOCAB.values()))
    metrics: dict | None = None
    minutes = ""
    n_tok = 0
    for acc, done_metrics in stream_summarize(
        cleaned, model=summary_model, title=title, agenda=agenda, vocab=terms
    ):
        minutes = acc
        if done_metrics is None:
            n_tok += 1
        else:
            metrics = done_metrics
        yield info(f"要約中（{summary_model}）… 出力 {n_tok} tok"), header + minutes, cleaned

    total = time.perf_counter() - t0
    summ_s = total - stt_s
    in_tok = metrics["input_tokens"] if metrics else 0
    out_tok = metrics["output_tokens"] if metrics else n_tok
    eval_s = metrics["eval_s"] if metrics else 0.0
    tps = (out_tok / eval_s) if eval_s > 0 else 0.0
    rtf = (total / dur) if dur > 0 else 0.0
    done = (
        f"✅ **完了** ｜ 🎧 音声長 **{dur:.1f}秒** ｜ ⏱ 合計 **{total:.1f}秒**"
        f"（文字起こし {stt_s:.1f}秒 / 要約 {summ_s:.1f}秒）\n\n"
        f"🔤 入力 **{in_tok}** tok ・ 出力 **{out_tok}** tok ・ 生成 **{tps:.1f} tok/s** ｜ "
        f"RTF（処理時間÷音声長）**{rtf:.2f}**"
    )
    yield done, header + minutes, cleaned


def build_demo():
    """gradio の Blocks UI を構築して返す。"""
    import gradio as gr

    with gr.Blocks(title="SynchroniNote") as demo:
        gr.Markdown(
            "# 🎙️ SynchroniNote — ローカル議事録\n"
            "音声を入れて **議事録を作成** を押すと、要約・決定事項・TODO の議事録が出ます。"
            "（完全ローカル / クラウド送信なし）"
        )
        with gr.Row():
            with gr.Column(scale=1):
                audio = gr.Audio(
                    sources=["microphone", "upload"],
                    type="filepath",
                    label="音声（マイク録音 または ファイル）",
                )
                title = gr.Textbox(label="会議名（任意）", placeholder="例: 開発定例")
                agenda = gr.Textbox(label="アジェンダ（任意）", placeholder="例: 進捗共有")
                with gr.Row():
                    summary_model = gr.Dropdown(
                        choices=SUMMARY_MODELS, value="gemma4:26b", label="要約モデル"
                    )
                    stt_model = gr.Dropdown(
                        choices=STT_MODELS, value="medium", label="文字起こしモデル"
                    )
                with gr.Accordion("🧭 モデルの選び方（クリックで開く）", open=False):
                    gr.Markdown(MODEL_HELP)
                btn = gr.Button("議事録を作成", variant="primary")
            with gr.Column(scale=1):
                info_out = gr.Markdown(value="ここに 音声長・経過時間・トークン数 が出ます。")
                minutes_out = gr.Markdown(value="ここに議事録が表示されます。")
                with gr.Accordion("文字起こし（ケバ取り済み）", open=False):
                    transcript_out = gr.Textbox(label="", lines=10)

        btn.click(
            make_minutes,
            inputs=[audio, title, agenda, summary_model, stt_model],
            outputs=[info_out, minutes_out, transcript_out],
        )
    return demo


def main() -> int:
    """ローカルサーバを起動する。"""
    demo = build_demo()
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
