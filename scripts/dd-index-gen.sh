#!/usr/bin/env bash
# =============================================================================
# dd-index-gen.sh — DD-INDEX.md の全量再生成（高速版）
#
# DDフォルダとアーカイブの全DDファイルからメタデータを抽出し、
# DD-INDEX.md を生成する。冪等（何度実行しても同じ結果）。
#
# 高速化: ファイルごとのサブプロセス起動を排除し、単一 awk で一括処理。
# 200ファイルでも1秒以内で完了する。
#
# 使い方:
#   bash scripts/dd-index-gen.sh
#   bash scripts/dd-index-gen.sh --dd-dir doc/DD --archive-dir doc/DD/archived
# =============================================================================

set -euo pipefail

# --- Default paths (adjust to your project) ---
DD_DIR="doc/DD"
ARCHIVE_DIR="doc/DD/archived"

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dd-dir)      DD_DIR="$2"; shift 2 ;;
        --archive-dir) ARCHIVE_DIR="$2"; shift 2 ;;
        *)             echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

INDEX_FILE="$DD_DIR/DD-INDEX.md"

# --- Validate directories ---
if [ ! -d "$DD_DIR" ]; then
    echo "ERROR: DD directory not found: $DD_DIR" >&2
    exit 1
fi

# --- Collect DD files ---
# NOTE: glob `DD-*.md` は DD-INDEX.md 自身もマッチするため明示的に除外する。
DD_FILES=()
for f in "$DD_DIR"/DD-*.md; do
    [ -f "$f" ] || continue
    [ "$(basename "$f")" = "DD-INDEX.md" ] && continue
    DD_FILES+=("$f")
done

ARCHIVE_FILES=()
if [ -d "$ARCHIVE_DIR" ]; then
    for f in "$ARCHIVE_DIR"/DD-*.md; do
        [ -f "$f" ] || continue
        [ "$(basename "$f")" = "DD-INDEX.md" ] && continue
        ARCHIVE_FILES+=("$f")
    done
fi

TOTAL=$(( ${#DD_FILES[@]} + ${#ARCHIVE_FILES[@]} ))

if [ "$TOTAL" -eq 0 ]; then
    # No DD files — write empty index
    cat > "$INDEX_FILE" <<'EMPTY_INDEX'
# DD 索引

> `bash scripts/dd-index-gen.sh` で自動生成。手動編集禁止。

## 進行中

| DD | 件名 | ステータス |
|----|------|-----------|

## 保留・見送り

| DD | 件名 | 理由 |
|----|------|------|

## 完了済み

| DD | 件名 | 主な成果 |
|----|------|---------|
EMPTY_INDEX
    echo "DD-INDEX.md updated: $INDEX_FILE (0 件)"
    exit 0
fi

# =============================================================================
# 高速メタデータ抽出: 単一 awk で全ファイルを一括処理
#
# 各ファイルの先頭6行だけ読み、以下を抽出:
#   - DD番号・タイトル: ファイル名から取得
#   - ステータス: メタデータテーブル行（日付で始まるパイプ区切り行）から取得
#
# 出力形式: location\tDD番号\tタイトル\tステータス\tソートキー
# =============================================================================

ENTRIES_TMP=$(mktemp)
trap 'rm -f "$ENTRIES_TMP"' EXIT

# head -v -n 6 を全ファイルに一括実行し、awk で解析
# head の出力形式: "==> filepath <==" + 内容行
# NOTE: -v を付けると、ファイルが1つだけ（例: アーカイブDDが1件）でも必ず
#       "==> filepath <==" ヘッダーが出力される。-v が無いと単一ファイル時に
#       ヘッダーが省略され、その entry が直前ファイルに吸収されて消える不具合になる。
{
    if [ ${#DD_FILES[@]} -gt 0 ]; then
        head -v -n 6 "${DD_FILES[@]}" 2>/dev/null
    fi
    if [ ${#ARCHIVE_FILES[@]} -gt 0 ]; then
        head -v -n 6 "${ARCHIVE_FILES[@]}" 2>/dev/null
    fi
} | awk '
# head -v -n 6 の出力を解析（-v により単一ファイルでも "==> filepath <==" ヘッダーが付く）

BEGIN {
    FS = "|"
    filepath = ""
    status = "N/A"
}

# ファイルヘッダー行
/^==> .* <==/ {
    # 前のファイルを出力
    if (filepath != "") {
        output_entry()
    }
    # 新しいファイルのパスを抽出
    gsub(/^==> /, "")
    gsub(/ <==.*/, "")
    filepath = $0
    status = "N/A"
    next
}

# メタデータテーブル行（日付で始まるパイプ区切り）
/^\| *[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
    if (status == "N/A") {
        # 4番目のフィールド（ステータス）を取得
        s = $4
        gsub(/^ +| +$/, "", s)
        if (s != "") status = s
    }
}

function output_entry() {
    # ファイル名からDD番号とタイトルを抽出
    fname = filepath
    # パスからファイル名部分だけ取得
    n = split(fname, parts, "/")
    basename = parts[n]
    # .md を除去
    sub(/\.md$/, "", basename)

    # DD番号とタイトルを分離
    idx = index(basename, "_")
    if (idx > 0) {
        dd_number = substr(basename, 1, idx - 1)
        title = substr(basename, idx + 1)
    } else {
        dd_number = basename
        title = "(タイトルなし)"
    }

    # ソートキー: DD-NNN → NNN の数値部分
    sort_key = dd_number
    gsub(/^DD[A-Z]*-/, "", sort_key)
    sub(/-.*/, "", sort_key)

    # location 判定: archived/ を含むか��うか
    location = (filepath ~ /archived\//) ? "archived" : "active"

    printf "%s\t%s\t%s\t%s\t%s\n", location, dd_number, title, status, sort_key
}

END {
    if (filepath != "") {
        output_entry()
    }
}
' > "$ENTRIES_TMP"

# --- 単一ファイルの場合のフォールバック ---
# head -6 が1ファイルだけだとヘッダーを出さないため、結果が空になる
if [ "$TOTAL" -eq 1 ] && [ ! -s "$ENTRIES_TMP" ]; then
    SINGLE_FILE=""
    if [ ${#DD_FILES[@]} -gt 0 ]; then
        SINGLE_FILE="${DD_FILES[0]}"
        LOCATION="active"
    else
        SINGLE_FILE="${ARCHIVE_FILES[0]}"
        LOCATION="archived"
    fi

    BASENAME=$(basename "$SINGLE_FILE" .md)
    if [[ "$BASENAME" == *_* ]]; then
        DD_NUM="${BASENAME%%_*}"
        TITLE="${BASENAME#*_}"
    else
        DD_NUM="$BASENAME"
        TITLE="(タイトルなし)"
    fi

    STATUS=$(head -6 "$SINGLE_FILE" | grep -E '^\| *[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1 | awk -F'|' '{gsub(/^ +| +$/, "", $4); print $4}')
    [ -z "$STATUS" ] && STATUS="N/A"

    SORT_KEY=$(echo "$DD_NUM" | sed 's/^DD[A-Z]*-//; s/-.*//')
    printf '%s\t%s\t%s\t%s\t%s\n' "$LOCATION" "$DD_NUM" "$TITLE" "$STATUS" "$SORT_KEY" > "$ENTRIES_TMP"
fi

# --- Generate DD-INDEX.md ---
{
    echo "# DD 索引"
    echo ""
    echo "> \`bash scripts/dd-index-gen.sh\` で自動生成。手動編集禁止。"
    echo ""

    # 進行中（ソートキー降順）
    echo "## 進行中"
    echo ""
    echo "| DD | 件名 | ステータス |"
    echo "|----|------|-----------|"
    # NOTE: grep が0件マッチで exit 1 を返すと pipefail+set -e で script 全体が落ちるため `|| true` で握りつぶす
    { grep '^active' "$ENTRIES_TMP" || true; } | sort -t$'\t' -k5,5nr | while IFS=$'\t' read -r _ dd_number title status _; do
        printf '| %s | %s | %s |\n' "$dd_number" "$title" "$status"
    done
    echo ""

    # 保留・見送り（自動検出不可のため空セクション。手動キュレーション用）
    echo "## 保留・見送り"
    echo ""
    echo "| DD | 件名 | 理由 |"
    echo "|----|------|------|"
    echo ""

    # 完了済み（ソートキー降順）
    echo "## 完了済み"
    echo ""
    echo "| DD | 件名 | 主な成果 |"
    echo "|----|------|---------|"
    { grep '^archived' "$ENTRIES_TMP" || true; } | sort -t$'\t' -k5,5nr | while IFS=$'\t' read -r _ dd_number title _ _; do
        printf '| %s | %s | |\n' "$dd_number" "$title"
    done
} > "$INDEX_FILE"

# --- Report ---
# NOTE: grep -c は0件マッチ時に "0" を出力して exit 1 するため、`|| echo 0` だと "0\n0" が混入する。`|| true` で exit だけ握る。
active_count=$(grep -c '^active' "$ENTRIES_TMP" 2>/dev/null || true)
archived_count=$(grep -c '^archived' "$ENTRIES_TMP" 2>/dev/null || true)

echo "DD-INDEX.md updated: $INDEX_FILE ($TOTAL 件: active=$active_count, archived=$archived_count)"
