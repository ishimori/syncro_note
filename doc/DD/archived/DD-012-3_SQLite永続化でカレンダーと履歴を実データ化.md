# DD-012-3: SQLite永続化でカレンダーと履歴を実データ化

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 完了（Phase 0-2 完了。残課題の S-02 保存一周は DD-012-9 Phase 5 実機E2E[新規作成]で確認済み） |

> 親DD: [DD-012 製品化（中核機能の実装と実用化）](DD-012_製品化_中核機能の実装と実用化.md)
> アプローチ: 標準（探索的実装。データ層の入出力は自動テストで固める）

## 目的

DD-007 で確定した [schema.sql](../spec/db/) を実装に接続し、**会議・文字起こし・議事録を SQLite に保存**する。これにより S-01 カレンダー（過去/予定会議）・S-03 議事録詳細・S-02 会議作成が**モックから実データ**になる。

## 背景・課題

- DB設計は DD-007 系で正式版まで確立（`doc/spec/db/` の データベース設計.md／データ辞書.md／schema.sql。schema.sql が唯一の正、実装は参照/ビルド時コピーで消費）。
- 画面 S-01/S-02/S-03 は DD-011 でモック実装済み（カレンダー描画・作成フォーム・議事録表示の見た目あり）。**残るは保存層との結線**。

## 検討内容（着手時の📐で確定）

- **DBの持ち主**: Rust(Tauri)側が所有しUIに供給するか／Python側が書くか／同一ファイルを両者が触るか。外部I/F（DB境界）に関わるため **Phase 0 で詳細化必須**。
- 書き込み点: 会議作成（S-02）→`meetings`、確定セグメント（S-05）→`segments`、最終議事録（S-07保存）→`final_minutes`＋`status='completed'`。
- 読み出し点: S-01（月内の会議＋ステータス）、S-03（過去議事録＋元タイムライン）。

## スコープ

- **やる**: DB初期化（schema.sql消費）・会議CRUD・セグメント保存・最終議事録保存・S-01/S-02/S-03 の実データ表示。ライフサイクル（scheduled→active→completed）。
- **やらない**: 同時編集/CRDT・クラウド同期・音声ファイル保持方針の詳細（設定は S-08 トグルのみ）。

## 依存

- 前提: **DD-007 schema.sql（確定済み）**。
- 連携: 最終議事録の保存は **DD-012-2** と接続（012-2 のファイル保存を DB 保存へ昇格）。
- 子DD: [DD-012-3-1 カレンダー確認用シードデータの整備](DD-012-3-1_カレンダー確認用シードデータの整備.md)（Phase2 のカレンダー表示確認を容易にする確認用サンプルデータを供給）。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 対象パス・🔬機械検証の精査（対象: `app/src-tauri/src/db.rs`新規・`Cargo.toml`・`app/src-tauri/build.rs`。検証=cargo test）
- [x] 📐 実装前詳細化トリガー判定（**DB境界＝外部I/F／スキーマ消費＝後戻り困難 → 詳細化必須**）。「DBの持ち主」を確定 → **下記「Phase 0 設計判断」参照**
- [x] 😈 Devil's Advocate（schema.sqlの二重管理・マイグレーション・同時オープン・文字コード）→ **下記DA記録参照**

#### Phase 0 設計判断: DBの持ち主 = **Rust(Tauri)の単独所有**
- **決定**: SQLite を開いて読み書きするのは **Rust(Tauri)側だけ**。Python サイドカーは従来どおり「stdin→計算→stdout(JSON Lines)」の純粋な使い捨て部品に保ち、**DBには一切触れない**。
- **根拠**:
  1. 既存 `pipeline/sidecar.py` は副作用なしの中継口（stdoutにJSON Lines）。DB書き込みを足すと設計が濁り、後のRust移植・テストも難しくなる。
  2. DBを必要とする画面 S-01/02/03/07 は全て Vue → `invoke` で Rust に問い合わせる。読み出しのたびに Python を spawn するのは不合理。
  3. **書き込み主体をRust一人に限定**すれば、SQLite WAL の多プロセス同時オープン/ロック競合（DA#3）が構造的に発生しない。
  4. schema.sql は `include_str!`（ビルド時埋め込み）で消費＝実装側に複製DDLを持たない（「唯一の正」原則・DA#1充足）。
- **データの流れ**: 録音セグメントは Python(stdout) → Rust中継 が `timeline_elements` へ書く（DD-011 3-C/012-1の経路の終端で）。本DDではまず会議CRUD・読み出し層と単体テストを固める。

### Phase 1: データアクセス層 ✅
- [x] 📐 実装前詳細化 → 👀レビュー（持ち主=Rust単独、Phase 0設計判断で確定済み）
- [x] schema.sql を `include_str!` で消費し DB 初期化（`app/src-tauri/src/db.rs`）。会議/参加者/タイムラインの読み書き層を実装
  - 実装関数: `open`/`init`（PRAGMA foreign_keys/WAL/synchronous）、`insert_meeting`・`get_meeting`・`list_meetings_by_month`・`update_meeting_status`・`save_final_minutes`、`insert_participant`・`list_participants`、`insert_timeline_element`・`list_timeline`
  - 純関数設計: id/created_at/updated_at は呼び出し側が確定して渡す（時計/UUIDに依存せずテストを決定的化）
- [x] 🔬 機械検証: `cargo test --manifest-path app/src-tauri/Cargo.toml --lib` → **8 passed; 0 failed**
  - schema適用＋既定設定投入 / 日本語タイトル完全往復(DA#4) / 月フィルタ＋昇順 / status遷移 / final_minutes保存→completed / timeline seq昇順 / **FK有効化で孤児挿入が失敗(DA#2)** / CASCADE削除
- [x] 😈 DA批判レビュー（下記 Phase 1 DA記録）

### Phase 2: 画面結線（S-01 / S-02 / S-03）
> 📌 確認を楽にする確認用サンプルデータは子DD [DD-012-3-1](DD-012-3-1_カレンダー確認用シードデータの整備.md) で供給。本Phaseのカレンダー目視確認は、そのシード投入状態で行うと空表示にならず確認しやすい。
- [x] Tauri command 層を新設（`app/src-tauri/src/db_commands.rs`）: `DbState`＋`list_meetings`/`create_meeting`/`get_meeting_detail`/`seed_demo`。`db.rs`(純rusqlite)は不変。`lib.rs` は `.setup()` でDBを開き manage＋ハンドラ登録の最小追記。**dev/本番でDBファイルを分離**（`*.dev.sqlite`/`*.sqlite`）しシードが本番DBに混入しないようにした
- [x] 型付き invoke ラッパー `app/src/api.ts`（Rust構造体に一致。ローカルISO生成 `localIso` 同梱）
- [x] `S02CreateMeeting.vue`: 保存して予約→`create_meeting`（id/時刻はJSで確定）→`/s01`
- [x] `S01Calendar.vue`: 当月会議を `list_meetings` で月表示（status色/今日/月送り）。dev は `seed_demo` を冪等投入。チップ→completedは `/s03?id=`、active→`/s05`、他→`/s02`
- [x] `S03MinutesDetail.vue`: completed一覧＋`get_meeting_detail`（本体＋参加者＋タイムライン）。final_minutes(Markdown)を軽量レンダリング
- [x] 🔬 機械検証: `cargo build` 緑 / `vue-tsc --noEmit` 緑 / **実ウィンドウ**（`tauri dev`＋`shot-window.ps1`）:
  - **S-01**: SQLite実データ6件（completed×3/active×1/scheduled×2）が当月に色分け表示・今日バッジ → `DD-012-3/s01_calendar_realdata.png`
  - **S-03**: チップ→詳細。会議名/日時/参加者(田中・鈴木)/最終議事録Markdown描画 → `DD-012-3/s03_detail_realdata.png`
  - **S-02**: フォーム描画確認 → `DD-012-3/s02_form.png`
  - ⚠️ **未自動化**: S-02「保存して予約」クリックの一周は自動操作で到達できず（UIA日本語引数が文字化け＋ボタンが画面外でホイール頭打ち）。保存の**書き込み経路は seed 経由で実証済み**（カレンダー=seed投入結果・詳細=seed参加者）。create_meeting は同じ `insert_meeting`/`insert_participant` の薄ラッパ＋型検査済 → **手動1回で確認できる残課題**（DA記録）
- [x] 😈 DA批判レビュー（下記 Phase 2 DA記録）

## 完了条件（DoD）

- 会議作成→保存→S-01カレンダー表示→S-03詳細閲覧が、実データ（SQLite）で一周する。
- schema.sql を唯一の正として消費している（実装側に重複定義を持たない）。

## ログ

### 2026-06-08
- DD作成（親 DD-012 の子）。DD-007 schema.sql を S-01/S-02/S-03 に結線し、モックを実データ化する永続化層として起票。
- **Phase 0 完了**: DBの持ち主を **Rust(Tauri)単独所有** に確定（Python はDB非接触）。📋精査・😈DA(4件)を記録。
- **Phase 1 完了（データアクセス層）**: `app/src-tauri/src/db.rs` 新規。schema.sql を `include_str!` で消費（複製DDLなし）。会議/参加者/タイムラインのCRUD実装。`cargo test --lib` で **8件緑**（日本語往復・FK有効化・seq順・CASCADE 等）。`Cargo.toml` に `rusqlite 0.32 (bundled)` 追加。
  - 付随修正: 並行作業中の DD-011 3-C コード（`lib.rs` `kill_sidecar`）の借用エラー（MutexGuard の生存期間）でビルド不能だったため、ガードを `take()` の行で落とす最小修正を実施（テスト緑化のため）。**3-C 担当セッションと編集が衝突する可能性あり** → 要すり合わせ。
- **次（Phase 2）**: Tauri command 公開＋ S-01/S-02/S-03 の `invoke` 結線（実ウィンドウ検証）。012-2 の保存はこの層の `save_final_minutes` に接続。
- **Phase 2 完了（画面結線）**: `db_commands.rs` 新設（`db.rs`純度維持）＋`lib.rs`最小配線（`.setup()`でDB open/manage、dev/本番でDBファイル分離）。`api.ts`＋S-01/S-02/S-03 を実データ結線。`cargo build`／`vue-tsc` 緑。**実ウィンドウ検証**（`tauri dev`＋3-Cの`shot-window.ps1`/`uia.ps1`）で S-01 がSQLite実データ6件を当月色分け表示、S-03 が `get_meeting_detail` の本体+参加者+議事録Markdownを表示することをスクショ確認（`DD-012-3/*.png`）。S-02 はフォーム描画を確認。
  - **残課題**: S-02「保存して予約」クリックの一周は自動操作で到達できず（UIA日本語引数の文字化け＋ボタン画面外）。保存の書き込み経路は seed 経由で実証済みのため、手動1回の確認で足る（Phase 2 DA#1）。
  - 付随: 検証で `app_data_dir/com.synchroninote.app/synchroni_note.dev.sqlite` を使用（本番DBと分離）。

### 2026-06-08（完了化）
- **DD完了**: 唯一の残課題だった「S-02『保存して予約』クリックの一周（手動確認）」は、後続 [DD-012-9](DD-012-9_S-01カレンダー操作強化_削除と移動ほか.md) の Phase 5 実機E2E（**新規→移動→編集→削除→元に戻す→コピー**＝ユーザー実機で全項目OK）で **新規作成（S-02 保存）の一周が実機確認済み**。同フェーズで「保存後に無通知」を実機検出→S-02 に成功トースト追加までしており、保存ボタン経路が実際に押下・通過したことが裏付けられた。
- DoD（作成→保存→S-01表示→S-03詳細が実データで一周／schema.sql を唯一の正として消費）を充足。ステータスを **完了** に更新。

---

## DA批判レビュー記録

### Phase 0 DA批判レビュー

**DA観点:** スキーマ消費とDB境界で「後戻りできない／壊れやすい」のはどこか？

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | schema.sql の二重管理（実装側にDDLを書き写すと正が2つになる） | 高 | 実装DDLと schema.sql が乖離 → どちらが正か不明 | 唯一の正の崩壊 | `include_str!("...schema.sql")` でビルド時埋め込み。実装に複製DDLを置かない |
| 2 | 接続ごと `PRAGMA foreign_keys=ON` の付け忘れ（SQLite既定OFF）でFKが効かない | 中 | 接続後にPRAGMA未実行→孤児行が作れてしまう | 制約の空振り | DB接続を作るヘルパに PRAGMA(foreign_keys/WAL/synchronous) を必ず同梱。テストで外部キー違反を検証 |
| 3 | 複数プロセスが同一 .sqlite を開きWALロック競合 | 中 | Python と Rust が同時書き込み→`database is locked` | 同時オープン | **書き込み主体をRust単独に限定**（設計判断で構造的に回避）。Pythonは触らない |
| 4 | 文字コード（日本語タイトル/本文）が化ける | 中 | cp932 環境でUTF-8前提が崩れる | 文字化け | SQLiteは内部UTF-8・rusqlite文字列もUTF-8。日本語を含む往復テストで担保 |

### Phase 1 DA批判レビュー

**DA観点:** データアクセス層で「テストは緑だが本番で崩れる」のはどこか？

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | `list_meetings_by_month` が `scheduled_start` の文字列前方一致頼り。TZ付き(`+09:00`)やUTC(`Z`)保存が混じると月境界がズレる | 中 | UTC保存の会議をローカル月で検索→取りこぼし/混入 | 時刻表現の前提崩れ | 暫定: 保存を**ローカルISO8601(無TZ)に統一**する前提を明文化。Phase 2 の書き込み口で固定し、必要なら範囲条件(`>= 'YYYY-MM-01' AND < 翌月`)へ強化 |
| 2 | `seq` の採番は本層の責務外（呼び出し側依存）。ライブ挿入で採番が競合すると `UNIQUE(meeting_id,seq)` 違反で落ちる | 中 | 2経路から同 seq を同時 insert | 採番の単一責任不在 | 書き込み主体がRust単独（設計判断）なので採番もRust側で一元化。012-1配線時に「次seq=現在max+1」をRust内で確定 |
| 3 | バンドルした sqlite3 のビルドにCツールチェーン依存（クリーン環境で `cc` 不在だと失敗） | 低 | MSVC無しPCで `cargo build` | ビルド再現性 | Tauri自体がMSVC前提のため実害小。012-6（配布）で同梱方針を最終確認 |

### Phase 2 DA批判レビュー

**DA観点:** 画面結線で「実機の別条件／別操作で崩れる」のはどこか？

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | S-02「保存して予約」クリックの一周が自動検証**未到達**（証跡なし） | 中 | UIA日本語引数の文字化け＋ボタン画面外でホイール頭打ち | 検証の穴 | 保存の書き込み経路は seed 経由で実証済み（同じ insert 関数）＋型検査済。**手動1回で確認**。恒久対策候補: 保存ボタンに英語の自動化用ラベル/`data-testid`、または UIA を ASCII で叩ける導線 |
| 2 | 単一接続を `Mutex` で共有。重い読み（大量履歴）中に書き込みが待たされ UI が固まりうる | 低 | 大量会議で list 中に create | 単一接続の直列化 | 現状データ量では実害なし。問題化したら接続プール or 読み取り専用接続を分離 |
| 3 | dev/本番でDBファイルを分けたが、**dev で投入した seed が dev DBに残り続ける**（毎回当月へ冪等投入） | 低 | 翌月 dev 起動→先月分 seed が残存 | dev データの蓄積 | dev限定なので許容。気になれば dev 起動時に古い月の seed を掃除、または seed を明示ボタン化 |
| 4 | フロントが渡す `scheduled_start` がローカルISO(無TZ)前提。将来TZ付きで保存するコードが混ざると月フィルタが破綻（Phase1 DA#1の再掲・実装で顕在化） | 中 | `toISOString()`(UTC)で保存する経路が紛れ込む | 時刻表現の前提崩れ | `api.ts` の `localIso` に集約し UTC生成を使わない方針を明記。`create_meeting` 経路を唯一の書き込み口にして固定 |
