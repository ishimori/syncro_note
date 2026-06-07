# DD-014-4: token emit 配線と DB 書込み集約＋実会議ストレステスト（P4-2/P4-3 統合回帰）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 未着手（DD-014-3 ＋ DD-013-3 後） |

> 親: [DD-014（P4-3 ホットパス Rust 移植）](DD-014_P4-3ホットパスRust移植_cpal_whisper-rs_Tokio.md) ／ アプローチ: E2E駆動（実会議音声で実機回帰）
> 依存: [DD-014-3](DD-014-3_Ollamaストリーム連携とTokioタスク設計.md) ／ **[DD-013-3](DD-013-3_左右コピーUIとネットワーク同期前提.md)（P4-2 と統合）**

## 目的

Rust whisper の token を `window.emit`（seq採番・is_final）で UI へ流し、`timeline_elements` 書込みを **T_state に集約**（DD-012-3 の「DB所有=Rust単独・Python副作用なし」原則を維持）。実 Rust→token→Yjs doc push を開通させ（P4-2 と統合）、**実会議音声で同時編集ストレステスト**を行い親DD-014 の定量目標を検証する。

## 背景・課題

- P4-2（DD-013）と P4-3（DD-014）が交わる統合点。実 Rust whisper の token を CRDT ドキュメントへ流し込む流路をここで初めて開通させる。
- whisper-rs 内製後も DB 書込みは Rust 単独所有を保つ（並行書込み制御 WAL/lock を新規実装）。

## 検討内容

**スコープイン**
- window.emit IPC による token streaming（seq採番・is_final フラグ）
- timeline_elements 書込みの **T_state 集約**と並行書込み制御（WAL/lock）。DD-012-3 の原則を維持
- 実 Rust whisper の token → window.emit → Yjs doc push の流路開通（[DD-013](DD-013_P4-2協調編集CRDT_AI追記と人間メモのマージ.md) と統合）
- 実会議音声（DD-010 sample02 再利用、複数話者・被り・長話）で同時編集 stress test
- 定量検証: 遅延-50%以上 / RTF改善15%以上 / CPU-20%以上、3〜5分連続でドロップ0・キューオーバーフロー0・マージ失敗0

**スコープアウト（重複回避）**
- CRDT マージのコア実装 → DD-013-2（本DDは流路開通と回帰のみ）
- 清書・保存 → DD-012-2 ／ シード → DD-012-3-1
- 配布バイナリ単一化 → 未決事項
- 話者ラベル確定UI → DD-012-5 / DD-004-1

## 決定事項

- DB 書込みは T_state に一本化（Rust単独所有を維持）。
- 定量目標（親DD-014 DoD）を実機で達成して初めて完了とする。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 対象ファイル明記（emit 配線・T_state DB書込み・統合テスト）
- [ ] 📐 実装前詳細化トリガー判定（並行書込み・統合回帰 → **詳細化要**）
- [ ] 😈 Devil's Advocate（T_state集約のrace・統合時のmerge失敗・実機再現性）

### Phase 1: token emit ＋ DB書込み集約
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] window.emit 配線＋timeline_elements の T_state 集約（WAL/lock）
- [ ] 🔬 機械検証: token が UI に反映、並行書込みで DB 破損なし

### Phase 2: P4-2/P4-3 統合回帰（実会議音声）
- [ ] 実 Rust whisper→token→Yjs doc push を開通（DD-013 と統合）
- [ ] 🔬 機械検証（実機）: 実会議音声でマージ失敗0・タイムアウト0、定量目標（遅延-50%/RTF+15%/CPU-20%、ドロップ0・オーバーフロー0）達成
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-014 の子・未実装）。P4-2(DD-013)との統合点のため DD-013-3 にも依存。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase N DA批判レビュー
（着手時に記録）
