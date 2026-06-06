#!/usr/bin/env bash
# =============================================================================
# pre-edit-guard.sh — 重要ファイルの編集をブロック
#
# PreToolUse hook for Edit|Write.
# Blocks editing of Claude settings, secrets, and auto-generated files.
# =============================================================================

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Normalize backslashes to forward slashes (Windows path compat)
FILE_PATH="${FILE_PATH//\\//}"
BASENAME=$(basename "$FILE_PATH")

# --- Protected files ---

# 1. Hook settings (prevent LLM from disabling its own guardrails)
case "$FILE_PATH" in
    *.claude/settings.local.json|*.claude/settings.json)
        echo "BLOCKED: Claude設定ファイル ($BASENAME) の編集は禁止されています。" >&2
        echo "  理由: Hook設定の改竄防止" >&2
        exit 2
        ;;
esac

# 2. Secret files
case "$FILE_PATH" in
    *.env|*.env.local|*.env.production)
        echo "BLOCKED: 環境変数ファイル ($BASENAME) の編集は禁止されています。" >&2
        echo "  理由: シークレット保護" >&2
        exit 2
        ;;
esac

# 3. Auto-generated DD-INDEX (use dd-index-gen.sh or /dd rebuild-index instead)
case "$FILE_PATH" in
    *DD-INDEX.md)
        echo "BLOCKED: DD-INDEX.md は自動生成ファイルです。手動編集禁止。" >&2
        echo "  更新: bash scripts/dd-index-gen.sh または /dd rebuild-index" >&2
        exit 2
        ;;
esac

# --- Add project-specific rules below ---
# Example: block linter config edits
# case "$BASENAME" in
#     eslint.config.js|.prettierrc*|biome.json)
#         echo "BLOCKED: リンター設定 ($BASENAME) の編集は禁止されています。" >&2
#         exit 2
#         ;;
# esac

exit 0
