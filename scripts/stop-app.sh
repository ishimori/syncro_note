#!/usr/bin/env bash
# =============================================================================
# stop-app.sh — Tauri 開発アプリを停止し、ポート1420を解放する
#
# `tauri dev` を Ctrl+C で止めても vite(node) がポート1420に残りがち
# （次回 start-app.sh が strictPort で起動失敗する原因）。
# このスクリプトはその後始末（ポート解放＋残った開発ウィンドウの終了）を行う。
#
# 使い方:  bash scripts/stop-app.sh
# =============================================================================
set -euo pipefail

PORT=1420
# このリポジトリの target 配下にある app.exe だけを対象にする（無関係な app.exe を巻き込まない）
APP_PATH_PAT='*\\syncro_note\\app\\src-tauri\\target\\*'
stopped=0

# 1) ポート1420 を占有しているプロセス(vite/node)を停止
if powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue){exit 0}else{exit 1}" >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
  echo "[停止] ポート $PORT（開発サーバ vite）を解放しました"
  stopped=1
fi

# 2) 残った開発用バイナリ app.exe（このリポジトリの target 配下のものだけ）を終了
if powershell.exe -NoProfile -Command "if (Get-Process app -ErrorAction SilentlyContinue | Where-Object { \$_.Path -like '$APP_PATH_PAT' }){exit 0}else{exit 1}" >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Get-Process app -ErrorAction SilentlyContinue | Where-Object { \$_.Path -like '$APP_PATH_PAT' } | Stop-Process -Force -ErrorAction SilentlyContinue" >/dev/null 2>&1 || true
  echo "[停止] 開発アプリ（app.exe）を終了しました"
  stopped=1
fi

if [ "$stopped" -eq 1 ]; then
  echo "停止しました。"
else
  echo "起動中の Tauri 開発アプリは見つかりませんでした（ポート $PORT は空き）。"
fi
