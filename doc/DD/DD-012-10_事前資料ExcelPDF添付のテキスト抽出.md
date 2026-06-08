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

## 決定事項

（Phase 0 で確定。現時点の素案＝上記ライブラリ採用・サイドカー抽出・local_path コピー方式）

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 抽出ライブラリの実測（xlsx=openpyxl / pdf=pymupdf or pdfplumber）。サンプルで本文取得・速度・文字化けを確認
- [ ] 📐 詳細化トリガー判定（新規テーブル配線・新規サイドカーモード・清書入力I/F変更 → **詳細化要**見込み）
- [ ] 😈 Devil's Advocate（巨大ファイル/暗号化PDF/画像PDF/文字コード/個人情報の取り扱い）

### Phase 1: 抽出パイプライン（Python サイドカー）
- [ ] `python/.../sidecar.py` に `--extract <path> --type <xlsx|pdf>`。`{"type":"extract","status":"done|error","text":...}` を emit
- [ ] 🔬 機械検証: サンプル xlsx/pdf で本文抽出（行数/文字数）・error 経路（壊れたファイル）。ruff
- [ ] 😈 DA批判レビュー

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
