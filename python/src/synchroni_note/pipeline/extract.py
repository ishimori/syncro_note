"""事前資料（Excel/PDF）の本文抽出（完全オフライン・DD-012-10）。

会議に添付した .xlsx / .pdf からテキストレイヤを抜き出し、清書バッチの入力
（前提資料セクション）に統合するための薄い抽出口。外部送信は一切しない
（openpyxl / pymupdf はローカルのみで完結）。

設計の正: doc/DD/DD-012-10_*.md の「Phase 0 設計判断」。
  - ``extract_text(path, file_type=None) -> ExtractResult``
  - 未対応拡張子は ``ValueError``、破損/暗号化はライブラリ例外を送出（呼び元が error に変換）。
  - 上限 ``EXTRACT_MAX_CHARS`` を超える本文は先頭優先でトリム（清書プロンプト膨張対策, DA#2）。
  - テキストゼロ（画像PDF等）は例外にせず ``empty=True`` で返す（UI 注意表示用, DA#1）。

対象外（将来・別DD）: 画像PDFのOCR、.docx/.pptx、パスワード解除。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 清書プロンプト膨張を防ぐ本文上限（先頭優先でトリム）。
# 1万字 ≒ 日本語で原稿用紙25枚相当。前提資料としては十分で、文脈を圧迫しない目安。
EXTRACT_MAX_CHARS = 10_000

# トリム時に末尾へ付す注記（清書側が「以降省略」と分かるように）。
_TRUNCATE_NOTE = "\n…（以降は文字数上限により省略）"


@dataclass(frozen=True)
class ExtractResult:
    """抽出結果。``text`` は上限トリム済み・正規化済みの本文。"""

    text: str
    chars: int  # トリム後の文字数
    truncated: bool  # 上限超過でトリムしたか
    empty: bool  # 抽出本文が実質ゼロ（空白のみ）か＝画像PDF等の注意表示用


def _trim(text: str) -> tuple[str, bool]:
    """先頭優先で ``EXTRACT_MAX_CHARS`` までに収める。超えたら注記を付す。"""
    if len(text) <= EXTRACT_MAX_CHARS:
        return text, False
    return text[:EXTRACT_MAX_CHARS] + _TRUNCATE_NOTE, True


def _extract_xlsx(path: Path) -> str:
    """xlsx をシート単位でテキスト化。

    ``data_only=True``＝数式は計算値を採用（清書には値が有用）。``read_only=True`` で
    大きなブックでも省メモリに走査する。各シートを ``# シート名`` 見出し＋行タブ連結で並べる。
    """
    import openpyxl  # 遅延 import（抽出時のみロード）

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        lines: list[str] = []
        for ws in wb.worksheets:
            lines.append(f"# {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append("\t".join(cells))
        return "\n".join(lines)
    finally:
        wb.close()


def _extract_pdf(path: Path) -> str:
    """pdf の全ページのテキストレイヤを連結（画像PDFは空になる＝OCR対象外）。"""
    import fitz  # pymupdf。遅延 import

    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _infer_type(path: Path) -> str:
    """拡張子から種別を推定。未対応は ``ValueError``。"""
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("xlsx", "pdf"):
        return suffix
    raise ValueError(f"未対応の拡張子: {path.suffix!r}（対応は xlsx / pdf）")


def extract_text(path: Path | str, file_type: str | None = None) -> ExtractResult:
    """添付ファイルから本文を抽出する（オフライン）。

    ``file_type`` 省略時は拡張子から推定。破損/暗号化ファイルは各ライブラリの例外を
    そのまま送出する（呼び元の sidecar が ``status="error"`` に変換する契約）。
    """
    path = Path(path)
    ftype = (file_type or _infer_type(path)).lower()
    if ftype == "xlsx":
        raw = _extract_xlsx(path)
    elif ftype == "pdf":
        raw = _extract_pdf(path)
    else:
        raise ValueError(f"未対応のtype: {ftype!r}（対応は xlsx / pdf）")

    text, truncated = _trim(raw)
    return ExtractResult(
        text=text,
        chars=len(text),
        truncated=truncated,
        empty=not raw.strip(),
    )
