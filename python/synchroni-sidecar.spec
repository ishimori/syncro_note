# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# synchroni-sidecar.spec — DD-012-6 配布用サイドカーの単一エントリ onedir ビルド
#
# 3つの sidecar(sidecar / summarize_sidecar / calendar_parse_sidecar) を
# dist_entry に集約した単一エントリを onedir で固める。頻繁に起動される
# サイドカーのため、onefile の毎回自己展開（初回遅延・AV誤検知）を避けて onedir。
#
# ビルド:
#   uv run --project python pyinstaller --noconfirm \
#     --distpath python/dist --workpath python/build python/synchroni-sidecar.spec
# 成果物: python/dist/synchroni-sidecar/synchroni-sidecar.exe（同フォルダに依存一式）
#   → Tauri の bundle.resources で resources/sidecar/ 配下へ同梱する（DD-012-6 Phase1）
# =============================================================================
import os

from PyInstaller.utils.hooks import collect_data_files

HERE = SPECPATH  # この .spec があるディレクトリ（= python/）。CWD非依存にするため使う。

# faster-whisper はパッケージ内に Silero VAD の .onnx アセットを同梱しており、これは
# 標準フックでは拾われない純データ。STT の VAD フィルタが実行時に要求するため明示収集する
# （未収集だと「silero_vad_v6.onnx … File doesn't exist」で文字起こしが落ちる）。
DATAS = collect_data_files("faster_whisper")

# 実行時に到達しない重量級依存を除外（DA: 同梱サイズ肥大対策）。
# STT(faster-whisper/av/ctranslate2) / 要約(ollama=HTTPのみ) / 抽出(openpyxl/pymupdf) /
# 収音(sounddevice) / 話者分離(onnxruntime/kaldi) のいずれも pandas/PIL/matplotlib 等は不要。
EXCLUDES = [
    "gradio", "pandas", "PIL", "pydub", "matplotlib",
    "scipy", "IPython", "tkinter", "pytest", "notebook",
]

a = Analysis(
    [os.path.join(HERE, "src", "synchroni_note", "pipeline", "dist_entry.py")],
    pathex=[os.path.join(HERE, "src")],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="synchroni-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX圧縮は無効（AV誤検知を避ける / 未導入環境での警告回避）
    console=True,         # stdin/stdout の JSON Lines 契約のため console サブシステム必須。
                          # 窓抑止は呼び出し側(Rust)が CREATE_NO_WINDOW で実施する。
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="synchroni-sidecar",
)
