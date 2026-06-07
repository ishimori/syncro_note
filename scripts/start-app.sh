#!/usr/bin/env bash
# =============================================================================
# start-app.sh — Tauri デスクトップアプリ(app/)を開発モードで起動する
#
# `npm run tauri dev` を前面で実行する。初回は Rust をコンパイルするため
# 数分かかる。アプリのウィンドウが開いたら準備完了。
#   停止: このターミナルで Ctrl+C 、または別ターミナルで stop-app.sh
#
# 使い方:  bash scripts/start-app.sh
# 前提:    Git Bash / Node.js(npm) / Rust(cargo) が入っていること
# ※ これは Tauri デスクトップアプリ用。Python の gradio UI は start-ui.sh 系。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
APP="$REPO/app"
PORT=1420

# --- 前提チェック ---
command -v npm   >/dev/null 2>&1 || { echo "[エラー] npm が見つかりません（Node.js を入れてください）"; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "[エラー] cargo が見つかりません（Rust を入れてください）"; exit 1; }
[ -d "$APP" ]                    || { echo "[エラー] app ディレクトリがありません: $APP"; exit 1; }

cd "$APP"

# --- 依存パッケージ（初回のみ）---
if [ ! -d "node_modules" ]; then
  echo "[1/2] 依存パッケージを取得します（初回のみ・数分）..."
  npm install
fi

# --- 残ったポート1420(vite)を解放（strictPort のため、占有されてると起動失敗する）---
if powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue){exit 0}else{exit 1}" >/dev/null 2>&1; then
  echo "[情報] ポート $PORT が使用中のため、古い開発サーバを停止します..."
  powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
fi

echo "[2/2] Tauri アプリを起動します（初回は Rust コンパイルで数分かかります）..."
echo "      ウィンドウが開いたら準備完了。停止は Ctrl+C または stop-app.sh"
exec npm run tauri dev
