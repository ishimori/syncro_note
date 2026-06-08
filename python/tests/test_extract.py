"""事前資料の本文抽出（DD-012-10）を Tauri/UI 非依存で検証する。

サンプル xlsx/pdf を tmp に生成して抽出本文・トリム・空判定・error 経路、
および sidecar ``--extract`` の JSON Lines 契約を固定する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synchroni_note.pipeline import extract
from synchroni_note.pipeline.extract import EXTRACT_MAX_CHARS, extract_text
from synchroni_note.pipeline.sidecar import main


def _make_xlsx(path: Path, rows: list[list[object]], title: str = "議題") -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _make_pdf(path: Path, text: str) -> Path:
    # 注: pymupdf の既定フォント(Helvetica)は CJK を埋め込めず日本語が点字化する。
    # よって PDF サンプルは ASCII 本文で生成する（日本語の通過確認は xlsx 側で担保）。
    # 実ユーザーの PDF はフォント埋め込み済みで日本語も抽出できる（Phase 0 実測・pymupdf 仕様）。
    import fitz

    doc = fitz.open()
    if text:  # 空文字なら本文なしの白紙ページ（画像PDF相当＝テキストレイヤ無し）
        doc.new_page().insert_text((72, 72), text, fontsize=12)
    else:
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_extract_xlsx_keeps_japanese_and_sheet_heading(tmp_path: Path) -> None:
    p = _make_xlsx(
        tmp_path / "s.xlsx",
        [["項目", "担当"], ["予算確認", "石森"], ["リリース", "2026年7月"]],
    )
    r = extract_text(p)
    assert "# 議題" in r.text  # シート見出し
    assert "予算確認\t石森" in r.text  # 行はタブ連結・日本語そのまま
    assert "2026年7月" in r.text
    assert not r.truncated and not r.empty
    assert r.chars == len(r.text)


def test_extract_pdf_reads_text_layer(tmp_path: Path) -> None:
    p = _make_pdf(tmp_path / "s.pdf", "Budget 12,000,000 JPY\nOwner Ishimori")
    r = extract_text(p)
    assert "Budget 12,000,000 JPY" in r.text
    assert "Owner Ishimori" in r.text
    assert not r.empty


def test_extract_type_inferred_from_suffix(tmp_path: Path) -> None:
    p = _make_pdf(tmp_path / "doc.pdf", "hello")
    assert extract_text(p, file_type=None).text.strip() == "hello"


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    bad = tmp_path / "note.docx"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_text(bad)


def test_empty_pdf_is_done_but_flagged_empty(tmp_path: Path) -> None:
    # 画像PDF（テキストレイヤ無し）相当 → 例外でなく empty=True で返す（DA#1）。
    p = _make_pdf(tmp_path / "blank.pdf", "")
    r = extract_text(p)
    assert r.empty is True
    assert r.text.strip() == ""


def test_long_text_is_truncated_with_note(tmp_path: Path) -> None:
    # 長文は xlsx の1セルに入れる（PDF は insert_text がページ外を切るため不適）。
    big = "あ" * (EXTRACT_MAX_CHARS + 500)
    p = _make_xlsx(tmp_path / "big.xlsx", [[big]])
    r = extract_text(p)
    assert r.truncated is True
    assert r.chars <= EXTRACT_MAX_CHARS + 40  # 注記ぶんの余白のみ
    assert "省略" in r.text


def test_broken_pdf_raises(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(Exception):  # noqa: B017  fitz.FileDataError 等（呼び元が error に変換）
        extract_text(broken)


# --- sidecar --extract の JSON Lines 契約 ---


def _run_sidecar(argv: list[str], capsys) -> list[dict]:
    rc = main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    return rc, [json.loads(line) for line in out if line]


def test_sidecar_extract_emits_done_line(tmp_path: Path, capsys) -> None:
    # xlsx で日本語が sidecar 契約(JSON Lines)を通っても化けないことも併せて固定する。
    p = _make_xlsx(tmp_path / "s.xlsx", [["前提資料の本文"]])
    rc, lines = _run_sidecar(["--extract", str(p)], capsys)
    assert rc == 0
    assert len(lines) == 1
    msg = lines[0]
    assert msg["v"] == 1 and msg["type"] == "extract" and msg["status"] == "done"
    assert "前提資料の本文" in msg["text"]
    assert msg["empty"] is False and msg["truncated"] is False


def test_sidecar_extract_emits_error_line_on_broken(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    rc, lines = _run_sidecar(["--extract", str(broken), "--type", "pdf"], capsys)
    assert rc == 1
    assert lines[-1]["type"] == "extract" and lines[-1]["status"] == "error"
    assert lines[-1]["where"] == "extract"


def test_extract_module_does_not_import_network_libs() -> None:
    # オフライン担保の補助チェック: extract モジュールが requests/urllib3 等を直接持ち込まない。
    src = Path(extract.__file__).read_text(encoding="utf-8")
    for banned in ("requests", "urllib", "httpx", "socket"):
        assert banned not in src
