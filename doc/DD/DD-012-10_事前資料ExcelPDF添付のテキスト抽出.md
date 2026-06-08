# DD-012-10: 事前資料（Excel/PDF）添付のテキスト抽出

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 未着手 |

> 親DD: [DD-012 製品化（中核機能の実装と実用化）](DD-012_製品化_中核機能の実装と実用化.md)
> アプローチ: 標準（探索的実装。抽出パイプラインは Python サイドカーで価値検証→ホットパスは後でRust移植の方針に沿う）
> 位置づけ: 会議の前提情報を厚くする。事前資料の本文を清書の入力に統合し、議事録の精度を上げる。

## 目的

会議に **Excel(.xlsx) / PDF(.pdf) を添付**し、**完全オフライン**でテキストを抽出して `attachments.extracted_text` に保存する。抽出本文を**清書バッチの入力に統合**し（基本設計 §「入力統合: …事前資料 `extracted_text`…」）、議事録の文脈精度を高める。

## 背景・課題

- `attachments` テーブルは設計済みだが**未実装**（[schema.sql](../../doc/spec/db/schema.sql) §4: `file_name`/`local_path`/`file_type∈{xlsx,pdf}`/`extracted_text`/`parse_status∈{pending,done,error}`）。
- 画面設計でも S-02 に「資料D&Dゾーン＋解析中スピナー」、S-03 に「添付 `q-chip`」が定義済みだが未配線（[画面設計書.md](../../doc/spec/画面設計書.md) §S-02/§S-03）。`parse_status` の pending/done/error をUIに出す前提。
- 基本設計の清書入力統合に `extracted_text` が含まれる（[基本設計書.md](../../doc/spec/基本設計書.md)）。現状の清書はタイムライン＋メモのみで、資料が反映されない。
- **セキュリティ要件**: AI処理は完全ローカル。抽出も外部送信なし（オフラインライブラリのみ）。

## 検討内容

- **抽出ライブラリ（オフライン必須）**:
  - xlsx → `openpyxl`（セル値をシート単位でテキスト化。数式は値優先）。
  - pdf → `pymupdf`(fitz) もしくは `pdfplumber`（テキストレイヤ抽出）。**画像PDFのOCRは対象外**（将来・別DD）。
  - 評価期は Python サイドカーに `--extract <path>` モードを追加して実行（whisper/LLM とは独立の軽量プロセス）。
- **取り込み手順**: 選択ファイルを**アプリ内へコピー**（`local_path`）→ `parse_status='pending'` で行作成 → サイドカー抽出 → 成否で `done`/`error`＋`extracted_text` 更新。大きすぎる本文は保存時に上限でトリム（清書前に再トリムも検討）。
- **清書統合**: 清書バッチ生成時に当該会議の `extracted_text`（done のもの）を**前提資料セクション**としてプロンプトに連結（既存の入力統合へ追加）。
- **UI**: S-02 で D&D 追加・一覧・状態（pending/done/error）表示・削除。S-03 で添付チップ表示（抽出済みは本文プレビュー可）。
  - ⚠️ **申し送り（DD-012-9 由来）**: 現在 `tauri.conf.json` は `dragDropEnabled:false`（カレンダー内 HTML5 DnD を有効化するため）。この状態だと **OS からのファイルドロップが無効**。本DDでファイルD&D取り込みを作るときは、`dragDropEnabled:true` に戻して Tauri の `tauri://drag-drop` イベントで受けるか、ファイル選択は**ダイアログ方式**（`plugin-dialog`）にするかを設計時に決める（カレンダーDnDと両立させる）。

## 決定事項

- **抽出ライブラリ＝openpyxl（xlsx）＋ pymupdf/fitz（pdf）に確定**（Phase 0 実測で本文取得・速度・文字化けなし・オフライン動作を確認）。pdfplumber は不採用（pymupdf が高速＝7.5ms/枚で十分）。
- 抽出は**独立モジュール `pipeline/extract.py`** に実装し、sidecar `--extract <path> [--type xlsx|pdf]` から呼ぶ（transcribe.py↔sidecar.py の分離パターン踏襲。pytest で単体検証）。
- **本文上限トリム**＝定数 `EXTRACT_MAX_CHARS`（先頭優先＋末尾に省略注記）。清書プロンプト膨張（DA#2）対策。
- **抽出ゼロ（画像PDF等）は `status='done'` かつ `empty=true`** で UI に注意表示（DA#1）。破損/暗号化は `status='error'`＋理由（DA#3）。
- ファイル取り込み導線（D&D vs ダイアログ）は **Phase 3 で決定**（上記 §UI の `dragDropEnabled` 申し送りに従う）。

### Phase 0 実測（スパイク）

`c:/tmp/spike_extract.py` で自作サンプル（日本語＋絵文字）を抽出。`uv run`（PYTHONUTF8=1）:

| 形式 | ライブラリ | 速度 | 文字化け | 異常系 |
|------|-----------|------|---------|--------|
| xlsx | openpyxl `load_workbook(read_only,data_only)` | 3.7ms | なし（日本語・絵文字✅・数値カンマ保持） | — |
| pdf  | pymupdf `page.get_text()` | 7.5ms/枚 | なし | 壊れPDF→`FileDataError` 例外（→error に倒せる） |

- **オフライン**: 両ライブラリとも抽出にネット不要（pymupdf 描画フォントもバンドル）。セキュリティ要件（外部送信なし）を満たす。

### Phase 0 設計判断（実装前の I/F 確定）

- **extract.py 公開関数**:
  - `EXTRACT_MAX_CHARS: int`（上限定数）
  - `extract_text(path: Path, file_type: str | None = None) -> ExtractResult` — `file_type` 省略時は拡張子から推定（`.xlsx`/`.pdf`）。`ExtractResult = {text:str, chars:int, truncated:bool, empty:bool}`。未対応拡張子/破損は `ValueError`/各ライブラリ例外を送出（呼び元が error に変換）。
  - 内部: `_extract_xlsx(path) -> str`（シート見出し`# {title}`＋行をタブ連結）／`_extract_pdf(path) -> str`（全ページ `get_text` 連結）。
- **sidecar 契約（extract モード, 1行=1JSON, `v:1`）**:
  - `{"type":"extract","status":"done","text":"..","chars":N,"truncated":bool,"empty":bool}`（成功）
  - `{"type":"extract","status":"error","message":"..","where":"extract"}`（失敗）
- **Tauri 側（Phase 2）**: `add_attachment(meeting_id, src_path)` がファイルを `app_data_dir/.../attachments/` へコピー→`parse_status='pending'` 行作成→sidecar `--extract` 実行→`done/error`＋`extracted_text` 更新。

## タスク一覧

### Phase 0: 事前精査 ✅
- [x] 📋 抽出ライブラリの実測（**openpyxl 3.1.5 / pymupdf 1.27**）→ スパイクで本文取得・速度・文字化けを確認（下記「Phase 0 実測」）。**両者とも純オフライン**で要件充足。**採用＝openpyxl＋pymupdf に確定**
- [x] 📐 詳細化トリガー判定 → **詳細化要**（新規テーブル配線＋新規サイドカーモード＋清書入力I/F変更）。実装前に下記「Phase 0 設計判断」に I/F を明記してから着手
- [x] 😈 Devil's Advocate（巨大ファイル/暗号化PDF/画像PDF/文字コード）→ 下記 Phase 0 DA（着手前先出し済み）。実測で #5 を追記

### Phase 1: 抽出パイプライン（Python サイドカー）✅
- [x] 抽出ロジックを独立モジュール [extract.py](../../python/src/synchroni_note/pipeline/extract.py) に実装（`extract_text()`／`ExtractResult{text,chars,truncated,empty}`／`EXTRACT_MAX_CHARS` トリム）。[sidecar.py](../../python/src/synchroni_note/pipeline/sidecar.py) に `--extract <path> [--type xlsx|pdf]` を追加し `{"type":"extract","status":"done|error",...}` を emit
- [x] 🔬 機械検証: [test_extract.py](../../python/tests/test_extract.py) 10件パス（xlsx日本語/見出し・pdfテキストレイヤ・拡張子推定・未対応→ValueError・空PDF→empty・上限トリム・破損→例外・sidecar done/error契約・ネットライブラリ非混入）。ruff クリーン。既存 sidecar/smoke テストも無傷
- [x] 😈 DA批判レビュー → Phase 0 DA #1/#2/#3/#5 を実装で担保（空=empty表示／上限トリム／破損=error／data_only維持）。下記 Phase 1 DA 追記なし（先出しで尽くした）

### Phase 2: BE（attachments の Tauri command＋db.rs）
- [ ] `db.rs`: `insert_attachment` / `list_attachments` / `update_attachment_parse`（status＋extracted_text）/ `delete_attachment`
- [ ] `db_commands.rs`: ファイルを `app_data_dir` 配下へコピー→行作成→サイドカー抽出→更新、の `add_attachment`、`list_attachments`、`remove_attachment`。`lib.rs` 登録・`api.ts` ラッパー
- [ ] 🔬 機械検証: `cargo test`（CRUD＋parse更新）。会議削除で添付も消える（CASCADE）
- [ ] 😈 DA批判レビュー

### Phase 3: FE（S-02 取り込み／S-03 表示）
- [ ] [S02CreateMeeting.vue](../../app/src/pages/S02CreateMeeting.vue): 資料D&D/選択・一覧・`parse_status` 表示・削除
- [ ] [S03MinutesDetail.vue](../../app/src/pages/S03MinutesDetail.vue): 添付チップ表示（抽出本文プレビュー）
- [ ] 🔬 機械検証: vue-tsc。実ウィンドウで添付→解析中→done 表示
- [ ] 😈 DA批判レビュー

### Phase 4: 清書統合
- [ ] 清書バッチの入力に `extracted_text`(done) を前提資料として連結（[基本設計書.md](../../doc/spec/基本設計書.md) の入力統合に沿う）
- [ ] 🔬 機械検証: 資料あり/なしで清書プロンプトに資料節が入る/入らない
- [ ] 😈 DA批判レビュー

## 完了条件（DoD）

- S-02 で Excel/PDF を添付でき、**オフラインで本文抽出**され `extracted_text` に保存される（pending→done/error がUIに出る）。
- 清書時に抽出本文が**前提資料として反映**される。
- 会議削除で添付（行・コピーファイル）も整理される。外部送信は一切なし。

## ログ

### 2026-06-08
- 起票（親 DD-012 の子）。ユーザー提案「事前にExcel/PDFを添付→テキスト抽出」を、設計済み未実装の `attachments` 実装として正式化。DD-012-9（S-01操作強化）から分離（性質が解析パイプラインで別物のため）。抽出は完全オフライン（openpyxl / pymupdf 等）。画像PDFのOCR・docx/pptx は対象外（将来）。
- **Phase 0 完了**: スパイクで openpyxl/pymupdf を実測（xlsx 3.7ms・pdf 7.5ms/枚、日本語・絵文字とも文字化けなし、破損PDFは例外で error 化可、両者オフライン）。**ライブラリ＝openpyxl＋pymupdf に確定**。📐詳細化＝要（上記「Phase 0 設計判断」に extract.py 公開I/F＋sidecar 契約を明記）。DA に実測由来 #5（openpyxl data_only の数式キャッシュ制約）を追記。`python` に `openpyxl`/`pymupdf` を依存追加（pyproject/uv.lock）。
- **Phase 1 完了**: `extract.py`（純粋な抽出口）＋ sidecar `--extract` モードを実装。pytest 10件パス・ruff クリーン。**テスト時の知見**: pymupdf 既定フォントは CJK 非対応で日本語PDF生成は点字化する→PDFサンプルは ASCII、日本語通過確認は xlsx で担保（実ユーザーのフォント埋め込みPDFは抽出可）。`insert_text` はページ外をクリップ→上限トリム検証は xlsx の長文セルで実施。次＝Phase 2（attachments の Tauri/db 配線）。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 0 DA（着手前の先出し）

**DA観点:** （オフライン制約／抽出品質／巨大・異常ファイル）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **画像PDF（スキャン）はテキストレイヤ無し**で抽出ゼロ | 中 | スキャンPDFを添付 | 抽出品質 | テキストレイヤのみ対応と明示。OCRは将来別DD。抽出0は `done`(空) ではなく注意表示 |
| 2 | **巨大本文で清書プロンプトが膨張**しモデル文脈を圧迫 | 中 | 大きなExcelを添付→清書 | 文脈/性能 | 保存時・清書前に文字数上限でトリム（先頭優先＋注記）。上限は定数化 |
| 3 | **暗号化/破損ファイル**で抽出例外 | 中 | パスワード付きPDF | 異常系 | `parse_status='error'` に倒し UI へ理由表示。会議作成自体は妨げない |
| 4 | **オフライン厳守**: ライブラリが外部フォントやネットを引かないこと | 高 | ネット遮断で抽出実行 | セキュリティ | ネット遮断環境で抽出が完結することを Phase 1 で検証（外部送信なしの担保） |
| 5 | **openpyxl `data_only=True` は「Excelが最後に保存した計算値」を読む**。openpyxl 等で生成・未計算の数式セルは `None`（=抽出欠落）。実ユーザーが Excel で保存したファイルは計算値キャッシュがあり値が入る（Phase 0 実測で確認した制約） | 低 | プログラム生成で未計算の数式xlsxを添付 | 抽出品質 | 実運用は「ユーザーがExcelで保存した実ファイル」なので実害低。テストのサンプルは Excel 保存相当（または数式を避ける）で固定。`data_only=True` は維持（数式文字列より値が清書に有用） |
