"""配布(PyInstaller)用の統一エントリポイント（DD-012-6）。

Rust 側 ``sidecar_base`` の配布経路は、同梱した単一 exe を
``synchroni-sidecar.exe <module> <module固有引数...>`` の形で起動する。
本モジュールは第1引数 ``<module>`` を見て、対応する各 sidecar の ``main(argv)``
へそのまま委譲する（薄いディスパッチャ）。開発時の
``uv run python -m synchroni_note.pipeline.<module>`` と同じ引数契約・同じ
JSON Lines 出力になる（フロント契約は不変）。

PyInstaller は「1エントリ＝1 exe」なので、3つの sidecar を1つの exe にまとめる
口として使う。exe 化前でも
``uv run python -m synchroni_note.pipeline.dist_entry <module> ...``
で同じ振り分け経路を検証できる。
"""

from __future__ import annotations

import sys

from synchroni_note.pipeline import (
    calendar_parse_sidecar,
    sidecar,
    summarize_sidecar,
)

# module 名 → その main(argv) -> int。Rust 側 sidecar_base が渡す第1引数と一致させる。
_DISPATCH = {
    "sidecar": sidecar.main,
    "summarize_sidecar": summarize_sidecar.main,
    "calendar_parse_sidecar": calendar_parse_sidecar.main,
}


def main(argv: list[str] | None = None) -> int:
    """第1引数のモジュール名で対応 sidecar の main へ委譲する。"""
    args = list(sys.argv[1:] if argv is None else argv)
    valid = ", ".join(_DISPATCH)
    if not args:
        sys.stderr.write(f"usage: dist_entry <module> [args...]  (module: {valid})\n")
        return 2
    module, rest = args[0], args[1:]
    entry = _DISPATCH.get(module)
    if entry is None:
        sys.stderr.write(f"unknown module: {module!r} (有効: {valid})\n")
        return 2
    return entry(rest)


if __name__ == "__main__":
    raise SystemExit(main())
