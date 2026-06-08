# DD-012-10: 事前資料（Excel/PDF）添付のテキスト抽出

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 進行中（Phase 0-4 実装/テスト完了・コミット済。残=Phase 5 実機E2E〔添付→抽出→表示→清書反映の一周〕） |

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

### Phase 2: BE（attachments の Tauri command＋db.rs）✅
- [x] [db.rs](../../app/src-tauri/src/db.rs): `Attachment` 構造体＋`insert_attachment`/`list_attachments`/`update_attachment_parse`/`get_attachment_path`/`delete_attachment`
- [x] [db_commands.rs](../../app/src-tauri/src/db_commands.rs): `add_attachment`（`app_data_dir/attachments/` へコピー→pending行→**ロック非保持で**抽出→done/error反映→確定行を返す）／`list_attachments`／`remove_attachment`（行＋ファイル後始末）。[lib.rs](../../app/src-tauri/src/lib.rs) に同期抽出ヘルパ `extract_text_blocking`（`uv run … --extract` を `output()` 待合せ→`type=extract` 行をパース）＋command登録。[api.ts](../../app/src/api.ts) に `Attachment`/`addAttachment`/`listAttachments`/`removeAttachment`
- [x] 🔬 機械検証: `cargo test --lib` 21件パス（添付 CRUD＋parse更新＋会議削除 CASCADE＋CHECK/FK 拒否の3件追加）。実CLI `uv run … sidecar --extract <xlsx/pdf>` が結果JSON 1行を emit することを実機確認（Rust が呼ぶ経路と同一）
- [x] 😈 DA批判レビュー → 下記 Phase 2 DA

### Phase 3: FE（S-02 取り込み／S-03 表示）✅（実装/型チェック）・実機E2EはPhase 5へ
- [x] **取り込み方式＝ファイル選択ダイアログに決定**（ユーザー合意）。`tauri-plugin-dialog` 導入（Rust/JS＋`lib.rs` 登録＋`capabilities/default.json` に `dialog:default`）。D&D不採用＝DD-012-9 の `dragDropEnabled:false`（カレンダーDnD）と競合するため
- [x] [S02CreateMeeting.vue](../../app/src/pages/S02CreateMeeting.vue): モックの資料カードを実データ化。「資料を追加」ボタン→`open()` で実パス取得→**2モード**（新規=保存待ち列に貯め保存時に取り込み／編集=即時 `addAttachment`）。一覧に `parse_status`（解析中/完了/失敗/本文なし）表示・削除。FK制約（添付は会議存在が前提）を2モードで吸収
- [x] [S03MinutesDetail.vue](../../app/src/pages/S03MinutesDetail.vue): 「事前資料」カード追加。`q-expansion-item` で抽出本文プレビュー（done のみ展開可）・状態バッジ
- [x] 🔬 機械検証: `vue-tsc --noEmit` パス・`cargo build` パス・Playwright で S-02 の資料カード描画を確認（空状態の案内文＋「資料を追加」）。**実ウィンドウでの 添付→解析中→done と本文プレビューは Tauri ランタイム専用 → Phase 5（実機E2E）へ**
- [x] 😈 DA批判レビュー → 下記 Phase 3 DA

### Phase 4: 清書統合 ✅（プロンプト統合＋継ぎ目）・**最終起動は予定→ライブ連結待ち**
- [x] [summarize.py](../../python/src/synchroni_note/pipeline/summarize.py) `build_minutes_prompt(materials=…)`：`done` 抽出本文を**書き起こしの前**に「事前資料」節として連結（空なら節なし）。`summarize`/`stream_summarize` も `materials` を透過
- [x] [summarize_sidecar.py](../../python/src/synchroni_note/pipeline/summarize_sidecar.py) `--materials-file PATH`：本文を読み `stream_summarize(materials=…)` へ。読込失敗は清書を止めず警告のみ
- [x] [lib.rs](../../app/src-tauri/src/lib.rs) `start_summarize(meeting_id?)`：`write_materials_file`（当該会議の done 添付の `extracted_text` を「## ファイル名＋本文」で連結→`app_data_dir/summarize_materials.txt`）→ `--materials-file` を付与。[session.ts](../../app/src/session.ts) に `meetingId`、[S06Generating.vue](../../app/src/pages/S06Generating.vue) が `meetingId` を渡す
- [x] 🔬 機械検証: [test_summarize_materials.py](../../python/tests/test_summarize_materials.py) 3件パス（資料あり→節が書き起こしの前に入る／無し・空白→節なし／title・agenda と共存）。`vue-tsc`・`cargo build` パス
- [x] 😈 DA批判レビュー → 下記 Phase 4 DA
- [x] ✅ **活性化＝並行セッションの「予定→ライブ連結」で接続済み**: [S05Realtime.vue](../../app/src/pages/S05Realtime.vue) が `route.query.id`→`linkedMeetingId`→`minutesSession.meetingId` を設定し（予定を開いて録音した場合）、[complete_meeting](../../app/src-tauri/src/db_commands.rs) で予定へ書き戻す縦串が別途実装された。これにより S-06 が `meetingId` を渡し→`start_summarize(meeting_id)`→`write_materials_file`→`--materials-file`→`build_minutes_prompt(materials)` が**端から端まで繋がる**（ad-hoc 録音は `meetingId=null` で従来どおり資料なし）。**実際に資料が清書へ載る一周は Phase 5 実機E2Eで確認**

## 完了条件（DoD）

- ✅ S-02 で Excel/PDF を添付でき、**オフラインで本文抽出**され `extracted_text` に保存される（pending→done/error/本文なし がUIに出る）※実機E2EはPhase 5。
- ✅ 清書時に抽出本文が**前提資料として反映**される → 統合・継ぎ目を実装/テストし、並行実装の「予定→ライブ連結」（`linkedMeetingId`/`complete_meeting`）で end-to-end が接続済み（実機での一周確認は Phase 5）。
- ✅ 会議削除で添付（行）は CASCADE 整理。外部送信は一切なし。※個別削除はファイルも消す。会議ごと削除時のコピーファイル掃除は既知の制約（Phase 2 DA#8）。

## ログ

### 2026-06-08
- 起票（親 DD-012 の子）。ユーザー提案「事前にExcel/PDFを添付→テキスト抽出」を、設計済み未実装の `attachments` 実装として正式化。DD-012-9（S-01操作強化）から分離（性質が解析パイプラインで別物のため）。抽出は完全オフライン（openpyxl / pymupdf 等）。画像PDFのOCR・docx/pptx は対象外（将来）。
- **Phase 0 完了**: スパイクで openpyxl/pymupdf を実測（xlsx 3.7ms・pdf 7.5ms/枚、日本語・絵文字とも文字化けなし、破損PDFは例外で error 化可、両者オフライン）。**ライブラリ＝openpyxl＋pymupdf に確定**。📐詳細化＝要（上記「Phase 0 設計判断」に extract.py 公開I/F＋sidecar 契約を明記）。DA に実測由来 #5（openpyxl data_only の数式キャッシュ制約）を追記。`python` に `openpyxl`/`pymupdf` を依存追加（pyproject/uv.lock）。
- **Phase 1 完了**: `extract.py`（純粋な抽出口）＋ sidecar `--extract` モードを実装。pytest 10件パス・ruff クリーン。**テスト時の知見**: pymupdf 既定フォントは CJK 非対応で日本語PDF生成は点字化する→PDFサンプルは ASCII、日本語通過確認は xlsx で担保（実ユーザーのフォント埋め込みPDFは抽出可）。`insert_text` はページ外をクリップ→上限トリム検証は xlsx の長文セルで実施。次＝Phase 2（attachments の Tauri/db 配線）。
- **追加UX（ユーザー要望・2026-06-08）**: 清書まで進めなくても**いつでも抽出テキストを確認**したい、という要望。データは取り込み時点で `savedAttachments[].extracted_text` に在るため**フロントのみ**で対応。S-02 の各 done 添付に「👁 抽出テキストを確認」ボタン→`q-dialog`（スクロール＋コピー）。S-03 のプレビュー（done のみ展開）と二面。
- **抽出の構造化（ユーザー指摘・2026-06-08）**: 「生のタブ羅列は LLM にも人にも価値が薄い＝構造を整えるべき」。`extract.py` の出力を**生タブ→構造化テキスト**へ刷新（後方互換なし・`extracted_text` の中身が変わる）。xlsx＝「（Excel・Nシート: …）概要」＋シートごとに「## シート「名」（行×列）」＋**Markdownテーブル**（`|`はエスケープ）、pdf＝「（PDF・Nページ）」＋「## p.N」＋本文。空（画像PDF等）は骨組みも保存せず `empty=True`（従来の「本文なし」UI/清書スキップを維持）。test_extract.py 更新＋pipeエスケープ等の検証追加（pytest 19・ruff・vue-tsc 緑）。**意味サマリ（LLM要約）は副作用（清書前の情報欠落・CPU遅延）を説明しユーザー判断に委ねた → 結果＝「構造化で十分（LLM要約は見送り）」で確定**（構造サマリ＝寸法/列見出しは決定的に同梱済）。
- **Phase 4 完了（実装/テスト）**: `build_minutes_prompt(materials=…)`で抽出本文を「事前資料」節として書き起こし前に連結（空なら節なし）。`summarize_sidecar --materials-file`／`start_summarize(meeting_id?)`＋`write_materials_file`（done非空のみ連結→一時ファイル）／S-06 が `meetingId` を渡す。pytest 3件＋`vue-tsc`/`cargo build`/`cargo test --lib`21件パス。**並行セッションの「予定→ライブ連結」（`linkedMeetingId`/`complete_meeting`）と噛み合い、予定を開いて録音→資料が清書へ載る経路が端まで接続**（実機一周は Phase 5）。当初「活性化は別作業待ち」と書いたが、並行実装で解消。DA #15-18 追記。**並行衝突メモ**: session.ts/S-05 は別セッションが meetingId 連結を実装したため本DDからは触れず（向こうの版を採用）。lib.rs は私の hunk のみ surgical stage（DD-012-5 の speakers 行は巻き込まない）。
- **Phase 2 完了**: db.rs に `Attachment`＋CRUD（insert/list/update_parse/get_path/delete）、db_commands に `add_attachment`/`list_attachments`/`remove_attachment`、lib.rs に同期抽出ヘルパ `extract_text_blocking`＋command登録、api.ts にラッパー。`cargo test --lib` 21件パス（添付3件追加）。実CLI で結果JSON emit を確認。DA #6-9 追記（抽出中はDBロック非保持／会議削除時のコピーファイル残置は既知の制約として許容）。次＝Phase 3（S-02 取り込みUI／S-03 表示・D&D vs ダイアログの設計判断）。

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

### Phase 2 DA（実装後）

**DA観点:** （DBロック保持／ゴミ行・ゴミファイル／長時間ブロック）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 6 | **抽出中の DB ロック保持**だと UI/他コマンドが数秒固まる（uv起動＋python import） | 高 | 添付追加中に他のDB操作 | 同時実行 | `add_attachment` は **insert→ロック解放→抽出（非保持）→再ロックで更新** の3区間に分割。抽出中はロックを持たない（コード化済み） |
| 7 | **コピー成功後に抽出失敗でゴミファイルが残らないか** | 中 | 壊れPDFを添付 | データ保全 | 仕様: コピー失敗は行作成前に早期return（ゴミ行なし）。抽出失敗は `error` 行＋ファイル残置（再抽出の余地）で許容。行は `remove_attachment` でファイルごと消せる |
| 8 | **会議ごと削除時、コピーした実ファイルがディスクに残る**（DB行は CASCADE で消えるがファイルは消えない） | 中 | 添付つき会議を S-01 で削除 | 後始末 | **既知の制約として許容**（オフライン端末内・容量影響小）。`remove_attachment`（個別削除）はファイルも消す。会議削除時の添付ファイル一括掃除は将来（別DD or Phase 追補） |
| 9 | **同期ブロックの体感**: add は uv 起動込みで数秒 await | 低 | 大きめPDFを添付 | UX | 頻度の低い会議前準備操作なので同期で十分。UI は Phase 3 で `pending` スピナー表示して吸収 |

### Phase 3 DA（実装後）

**DA観点:** （新規のFK制約／実パス取得／状態の取りこぼし）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 10 | **新規会議は meeting 行が無く、添付の FK が張れない**。作成前に `add_attachment` すると失敗 | 高 | 新規作成画面で資料追加→保存前 | データ整合 | 新規は**保存待ち列**に貯め、`create_meeting` 成功**後**に採番済み id で取り込む。id は `meetingId`（新規は一度だけ採番）で作成と一致させる。編集は会議が在るので即時 |
| 11 | **webView の `input[type=file]` は実パスを返さない**（Tauri セキュリティ）。コピー元パスが取れない | 高 | D&D/HTML input で添付 | 実装制約 | `tauri-plugin-dialog` の `open()` で**絶対パス**を取得し `add_attachment(src_path)` に渡す（BE のコピー設計と一致） |
| 12 | **抽出ゼロ(画像PDF)が「完了」に見える** | 中 | 画像PDFを添付 | 抽出品質 | `done` かつ `extracted_text` 空を `isEmptyExtract` で判定し「本文なし（画像PDFの可能性）」をオレンジ表示（S-02）。S-03 は本文プレビューを無効化＋「本文なし」バッジ |
| 13 | **保存前に追加→キャンセルでゴミが残らないか** | 低 | 新規で資料追加→キャンセル | データ保全 | 新規はコピー/抽出を保存時まで遅延＝キャンセルなら何も書かない（ゴミ行/ファイルなし）。保存待ちは×で個別取消可 |
| 14 | **実機E2E（ダイアログ→抽出→表示）は Tauri 専用** | 中 | 実ウィンドウで添付 | 検証境界 | Playwright は描画のみ確認。添付の一周は **Phase 5（実機E2E）** でユーザー実機確認 |

### Phase 4 DA（実装後）

**DA観点:** （資料の巨大化／資料読込失敗／資料の選別）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 15 | **複数資料の連結で清書プロンプトが膨張** | 中 | done資料を多数添付→清書 | 文脈/性能 | 各資料は抽出時に `EXTRACT_MAX_CHARS` でトリム済み（Phase 1）。`write_materials_file` は done かつ非空のみ連結。将来必要なら合計上限も検討 |
| 16 | **materials ファイル読込失敗で清書全体が落ちないか** | 中 | materials-file を壊す/消す | 異常系 | `summarize_sidecar` は読込失敗を `OSError` で握り潰し**書き起こしのみで続行**（清書は止めない）。`write_materials_file` も done資料が無ければ None＝引数を付けない |
| 17 | **error/空(本文なし)資料を清書に混ぜない** | 中 | error/画像PDFを添付→清書 | 入力品質 | `write_materials_file` は `parse_status=='done'` かつ `extracted_text` 非空のみ採用（error・空はスキップ） |
| 18 | **ad-hoc 録音に資料が無いのに資料節が出ないか** | 低 | 予定を開かず録音→清書 | 整合 | `meetingId=null` のとき materials なし＝資料節なし（`build_minutes_prompt` は空 materials で節を出さない）。テストで固定 |
