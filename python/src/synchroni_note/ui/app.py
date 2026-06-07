"""SynchroniNote 評価期UI（gradio）: ブラウザで音声→議事録Markdown。

起動:
    uv run synchroni-note-ui
    # ブラウザで http://127.0.0.1:7860 を開く

マイク録音 or 音声ファイルを入れて「議事録を作成」を押すと、議事録が表示される。
完全ローカル（クラウド送信なし）。本番UIは Quasar/Tauri（別途）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from synchroni_note.pipeline.cleaning import clean_text
from synchroni_note.pipeline.cli import DEMO_VOCAB
from synchroni_note.pipeline.summarize import summarize
from synchroni_note.pipeline.transcribe import transcribe, transcript_text

SUMMARY_MODELS = ["gemma4:26b", "qwen3:8b", "gemma4:e4b"]


def make_minutes(
    audio_path: str | None,
    title: str,
    agenda: str,
    summary_model: str,
    stt_model: str,
) -> Iterator[tuple[str, str]]:
    """音声→議事録を生成し、(議事録Markdown, ケバ取り済み書き起こし) を順次返す。

    gradio のジェネレータ出力で進捗（文字起こし中→要約中→完了）を表示する。
    """
    if not audio_path:
        yield "⚠️ 先に音声を録音するか、ファイルを入れてください。", ""
        return

    yield f"⏳ 文字起こし中（faster-whisper {stt_model} + VAD）…", ""
    segments = transcribe(Path(audio_path), model_size=stt_model)
    raw = transcript_text(segments)
    cleaned = clean_text(raw, vocab=DEMO_VOCAB)

    yield f"⏳ 要約中（{summary_model}）… 文字起こしは下のパネルに出ています。", cleaned
    terms = sorted(set(DEMO_VOCAB.values()))
    minutes = summarize(cleaned, model=summary_model, title=title, agenda=agenda, vocab=terms)

    header = f"# {title}\n\n" if title else ""
    yield header + minutes, cleaned


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
                        SUMMARY_MODELS, value="gemma4:26b", label="要約モデル"
                    )
                    stt_model = gr.Dropdown(
                        ["medium", "base", "small"], value="medium", label="文字起こしモデル"
                    )
                btn = gr.Button("議事録を作成", variant="primary")
            with gr.Column(scale=1):
                minutes_out = gr.Markdown(value="ここに議事録が表示されます。")
                with gr.Accordion("文字起こし（ケバ取り済み）", open=False):
                    transcript_out = gr.Textbox(label="", lines=10)

        btn.click(
            make_minutes,
            inputs=[audio, title, agenda, summary_model, stt_model],
            outputs=[minutes_out, transcript_out],
        )
    return demo


def main() -> int:
    """ローカルサーバを起動する。"""
    demo = build_demo()
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
