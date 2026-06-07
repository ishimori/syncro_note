#!/usr/bin/env bash
# =============================================================================
# doc-index-check.sh — ドキュメント索引（doc/INDEX_MAP.md）のドリフト検知
#
# doc/ 配下の .md と INDEX_MAP.md の内容を突き合わせ、以下を検出する:
#   1. [未登録]   doc/ にあるのに INDEX_MAP.md に載っていない .md
#   2. [リンク切れ] INDEX_MAP.md 内のリンク先ファイルが存在しない
#
# 読み取り専用（ファイルを書き換えない）。冪等。
#
# 対象外（DDは別管理 → DD-INDEX.md / dd-index-gen.sh）:
#   - doc/DD/ 配下すべて（アーカイブ doc/DD/archived/ を含む）
#   - INDEX_MAP.md 自身
#
# 使い方:
#   bash scripts/doc-index-check.sh            # 検知してレポート（exit 0）
#   bash scripts/doc-index-check.sh --strict   # ドリフトがあれば exit 1（CI/フック用）
#
# リポジトリルートで実行すること。
# =============================================================================

set -euo pipefail

DOC_DIR="doc"
INDEX_FILE="$DOC_DIR/INDEX_MAP.md"
STRICT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict) STRICT=1; shift ;;
        --doc-dir) DOC_DIR="$2"; INDEX_FILE="$DOC_DIR/INDEX_MAP.md"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ ! -f "$INDEX_FILE" ]; then
    echo "ERROR: 索引ファイルが見つかりません: $INDEX_FILE" >&2
    exit 1
fi

echo "== doc-index-check: $INDEX_FILE =="

drift=0

# -----------------------------------------------------------------------------
# 0. INDEX_MAP.md からリンク先を一括抽出（']( ... )' の中身）
#    - ALL_TMP:  全リンク先（リンク切れチェック用、../ や http も含む）
#    - REG_TMP:  doc/ 相対の「登録済みパス集合」（未登録チェック用。../・http・# を除外）
# -----------------------------------------------------------------------------
ALL_TMP=$(mktemp)
REG_TMP=$(mktemp)
trap 'rm -f "$ALL_TMP" "$REG_TMP"' EXIT

# CRLF を除去しつつリンク先を抽出
grep -oE '\]\([^)]+\)' "$INDEX_FILE" | sed -E 's/^\]\(//; s/\)$//; s/\r$//' > "$ALL_TMP"

while IFS= read -r target; do
    [ -z "$target" ] && continue
    case "$target" in
        http://*|https://*|mailto:*|\#*|../*) continue ;;
    esac
    path="${target%%#*}"                        # アンカー(#...)を除去
    [ -n "$path" ] && printf '%s\n' "$path"
done < "$ALL_TMP" | sort -u > "$REG_TMP"

# -----------------------------------------------------------------------------
# 1. 未登録チェック: doc/ 配下の .md（DD配下・INDEX_MAP自身を除く）が
#    登録済みパス集合に「完全一致」で含まれるか（grep -Fx で部分一致誤検知を防止）
# -----------------------------------------------------------------------------
unregistered=()
while IFS= read -r -d '' f; do
    rel="${f#"$DOC_DIR"/}"                      # doc/ を除いた相対パス（例: plan/企画書.md）
    if ! grep -Fxq -- "$rel" "$REG_TMP"; then
        unregistered+=("$rel")
    fi
done < <(
    find "$DOC_DIR" -type f -name '*.md' \
        -not -path "$DOC_DIR/DD/*" \
        -not -path "$INDEX_FILE" \
        -print0 | sort -z
)

if [ ${#unregistered[@]} -gt 0 ]; then
    drift=1
    echo ""
    echo "[未登録] 以下の doc ファイルが INDEX_MAP.md に未登録です（追記してください）:" >&2
    for u in "${unregistered[@]}"; do
        echo "  - $u" >&2
    done
fi

# -----------------------------------------------------------------------------
# 2. リンク切れチェック: INDEX_MAP.md 内の相対リンク先が実在するか
#    （http(s):// と #アンカーのみのリンクは対象外）
#    リンクは INDEX_MAP.md（= doc/ 直下）からの相対パスとして解決する。
# -----------------------------------------------------------------------------
broken=()
while IFS= read -r target; do
    [ -z "$target" ] && continue
    case "$target" in
        http://*|https://*|mailto:*|\#*) continue ;;
    esac
    path="${target%%#*}"                        # アンカー(#...)を除去
    [ -z "$path" ] && continue
    # INDEX_MAP.md は doc/ 直下にあるため、リンクは "$DOC_DIR/$path" で解決
    if [ ! -e "$DOC_DIR/$path" ]; then
        broken+=("$target")
    fi
done < "$ALL_TMP"

if [ ${#broken[@]} -gt 0 ]; then
    drift=1
    echo ""
    echo "[リンク切れ] INDEX_MAP.md 内のリンク先が存在しません（修正してください）:" >&2
    for b in "${broken[@]}"; do
        echo "  - $b" >&2
    done
fi

# -----------------------------------------------------------------------------
# 結果
# -----------------------------------------------------------------------------
echo ""
if [ "$drift" -eq 0 ]; then
    echo "OK: $INDEX_FILE は $DOC_DIR/ 配下（DD配下除く）と同期しています。"
    exit 0
fi

echo "→ $INDEX_FILE を更新してください。詳細: $INDEX_FILE「メンテナンス方針」" >&2
if [ "$STRICT" -eq 1 ]; then
    exit 1
fi
exit 0
