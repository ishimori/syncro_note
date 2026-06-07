#!/usr/bin/env bash
# =============================================================================
# build-app.sh — Tauri デスクトップアプリ(app/)を配布用にビルドする
#
# `npm run tauri build` を実行し、インストーラ/実行ファイルを生成する。
# Rust のリリースビルドのため、特に初回は時間がかかる（数分〜十数分）。
#
# 成果物: app/src-tauri/target/release/bundle/ 以下
#   - nsis/*-setup.exe   （インストーラ）
#   - msi/*.msi          （MSI インストーラ）
#   実行ファイル単体は app/src-tauri/target/release/app.exe
#
# 使い方:  bash scripts/build-app.sh
# 前提:    Git Bash / Node.js(npm) / Rust(cargo) が入っていること
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
APP="$REPO/app"

# --- 前提チェック ---
command -v npm   >/dev/null 2>&1 || { echo "[エラー] npm が見つかりません（Node.js を入れてください）"; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "[エラー] cargo が見つかりません（Rust を入れてください）"; exit 1; }
[ -d "$APP" ]                    || { echo "[エラー] app ディレクトリがありません: $APP"; exit 1; }

cd "$APP"

# --- 依存パッケージ（初回のみ）---
if [ ! -d "node_modules" ]; then
  echo "[1/2] 依存パッケージを取得します（初回のみ）..."
  npm install
fi

echo "[2/2] リリースビルドを実行します（時間がかかります）..."
npm run tauri build

BUNDLE="$APP/src-tauri/target/release/bundle"
echo ""
echo "完了。成果物はこちら:"
echo "  $BUNDLE/"
ls -1 "$BUNDLE" 2>/dev/null || echo "  （bundle ディレクトリが見つかりません。上のログを確認してください）"
