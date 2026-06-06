#!/usr/bin/env bash
# =============================================================================
# post-bash-dd-archive-reminder.sh — DD アーカイブ後の INDEX 更新リマインダー
#
# PostToolUse hook for Bash.
# Detects mv commands targeting archived/ with DD files and reminds to update INDEX.
# Non-blocking (always exits 0).
# =============================================================================

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/')

# .md ファイルの移動のみに反応（フォルダ移動での二重発火を防止）
if echo "$COMMAND" | grep -qE 'mv.*DD-.*\.md.*archived/'; then
    echo "[Hook] DD をアーカイブしました。DD-INDEX.md を更新してください。" >&2
    echo "  -> スクリプト: bash scripts/dd-index-gen.sh" >&2
    echo "  -> または: /dd rebuild-index" >&2
fi

exit 0
