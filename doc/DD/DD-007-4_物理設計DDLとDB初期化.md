# DD-007-4: 物理設計（schema.sql＋DB初期化）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | レビュー待ち |

> 親: [DD-007](DD-007_データベース基本設計.md) ／ 前: [DD-007-3](DD-007-3_論理設計ER図.md)
> アプローチ: 標準（探索的実装＋機械検証中心）
> **方針（簡素化）**: 過去データの移行は不要（ユーザー確認済み）。**マイグレーション機構は作らない**。起動時に `schema.sql` を冪等適用するだけ。

## 目的

ER図（DD-007-3）を SQLite の物理スキーマ（実行可能な DDL）に落とし、**起動時に schema.sql を適用するとテーブルが生成される**ことを実機検証する。版管理・差分適用は行わない。

## 背景・課題

- [File 1 ステップ2](../plan/要件/1_共通仕様.md#L131-L134): 起動時にテーブルが自動生成されること。
- [SSOT §3.4](../spec/基本設計書.md#L153): WAL有効・別タスクでバッチ flush（ホットパスを止めない）。
- 評価期は Python、製品期は Rust。**schema.sql を両者で共有するプレーンDDLの正とする**（言語非依存）。
- **移行不要の割り切り**: スキーマを変えたくなったら `.sqlite` を削除して作り直す。`ALTER TABLE`・版番号・ロールバックは不採用（理由は [スキーマ適用方針.md](DD-007-4/スキーマ適用方針.md)）。

## 検討内容

- DDL配置: `python/`（評価期）と将来の Tauri 側で共有する schema.sql の置き場所と読み込み方法。
- 索引: カレンダー一覧（status, scheduled_start）、議事録詳細（meeting_id）、タイムライン順序（meeting_id, seq）。
- 制約: FK ON DELETE CASCADE（参加者/用語/資料/タイムライン/話者）、SET NULL（話者→参加者）、NOT NULL、CHECK（status 等の enum）。
- 設定: WAL（`journal_mode=WAL`）、接続ごと `foreign_keys=ON`。

## 決定事項

成果物 [schema.sql](DD-007-4/schema.sql) ＋ [スキーマ適用方針.md](DD-007-4/スキーマ適用方針.md) に集約。要点:
- 全7テーブルDDL＋索引5本＋CHECK制約。`CREATE ... IF NOT EXISTS`＋`INSERT OR IGNORE` で**冪等**。
- **マイグレーションなし**: 起動時に schema.sql を流すだけ。版管理（user_version）・差分適用・ロールバック・バックアップは**不採用**。
- スキーマ変更時は `.sqlite` を削除して再生成（過去データ移行不要の前提）。
- 接続ごとに **`PRAGMA foreign_keys=ON`** 必須（CASCADE/SET NULL を効かせる）。`journal_mode=WAL`。
- schema.sql を単一の正とし評価期(Python)／製品期(Rust)で共有。実装時に各ランタイム配下へ移設。
- **🔬 :memory: 適用検証 PASS**（7表＋索引生成・FK整合・2回適用冪等・CASCADE全削除・既定設定1行）。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 各テーブルDDLに「対応ER要素」「索引」「制約」を併記
- [x] 📐 詳細化トリガー判定 → スキーマ確定＝該当。ただし移行不要のためマイグレーション設計は除外
- [x] 😈 Devil's Advocate: CASCADE 消し過ぎ／FK無効化リスク → DA記録参照

### Phase 1: DDL・適用方針の確定
- [x] schema.sql の配置場所・読み込み経路（評価期Python / 製品期Rust）を特定 → [スキーマ適用方針.md](DD-007-4/スキーマ適用方針.md) §3
- [x] 適用方式（起動時 schema.sql 冪等適用のみ・版管理なし）を決定 → 方針 §1〜2
- [ ] 👀 **ユーザーレビュー**（合意後に実装フェーズへ）

### Phase 2: DDL 実装
- [x] [schema.sql](DD-007-4/schema.sql) に全テーブルDDL＋索引＋CHECK＋PRAGMA（WAL/foreign_keys）を記述
- [x] 🔬 機械検証: `:memory:` へ適用 → 全テーブル/索引生成・`foreign_key_check` エラー0
- [x] 🔬 機械検証: 2回連続適用で冪等（重複エラーなし）
- [x] 😈 DA批判レビュー（下記）

### Phase 3: 通し確認
- [x] ダミー会議1件の INSERT→集約読み出しが成立
- [x] 🔬 機械検証: FK CASCADE で meeting 削除時に子（participants/timeline/speaker）が全削除
- [x] 😈 DA批判レビュー（下記）

## ログ

### 2026-06-07
- DD作成
- Phase 1〜3 実施。schema.sql＋スキーマ適用方針を作成。`:memory:` 適用検証 全PASS。
- レビュー指摘により**マイグレーション機構を廃止**（過去データ移行不要のため）。版管理・差分適用・ロールバックを削除し「起動時 schema.sql 冪等適用のみ」へ簡素化。DD/ファイル名から「マイグレーション」を除去。**レビュー待ち**。
- 🔬検証コマンド: `python -c "..."`（schema.sql を executescript×2→テーブル/索引/FK/CASCADE/冪等を確認、すべてPASS）
- SSOT照合監査を反映: schema.sql の `seq` コメントに「ai/memo共通の全順序キー・memoも挿入位置でseq採番・ORDER BY seq」を明記。再適用検証 再PASS。防御的CHECK群(kind↔speaker_id / 非負 / completed→final_minutes 等)は実害なしのため見送り(DD-007 親ログ参照)。

---

## DA批判レビュー記録

### Phase 1〜3 DA批判レビュー

**DA観点:** FK・WAL下の整合／簡素化で抜ける点は？

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | SQLite は接続ごとに foreign_keys が既定OFF。ONし忘れると CASCADE/SET NULL が無効化 | 高 | PRAGMA未実行で meeting 削除→子が残る | FK整合 | ✅ 方針 §4・schema冒頭・接続コードで必須化を明記 |
| 2 | `CREATE TABLE IF NOT EXISTS` は既存テーブルに定義変更を反映しない | 中 | schema.sql 編集後も旧 .sqlite が残ると旧定義のまま | 簡素化の代償 | ✅ 「定義を変えたら .sqlite を削除して再生成」をルール化（方針 §2） |
| 3 | AUTOINCREMENT で sqlite_sequence 表が生成される | 低 | テーブル一覧に出る | スキーマ純度 | ❌不要: SQLite仕様。許容 |
