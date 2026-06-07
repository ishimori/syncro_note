# DD-013-1: Yjs 導入と Vue3 バインディング基盤（mock AI で同時編集の土台）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 未着手（DD-011 完了済みのため着手可） |

> 親: [DD-013（P4-2 協調編集 CRDT）](DD-013_P4-2協調編集CRDT_AI追記と人間メモのマージ.md) ／ アプローチ: 標準（探索的実装）
> 前提: [DD-011（Tauri 2ペイン骨格・P4-1）](DD-011_Phase4_Tauri2ペインUI骨格_Python中身に接続.md) 完了

## 目的

Yjs ライブラリをフロント（Tauri/TypeScript/Vue3）に導入し、Yjs ドキュメント初期化・Vue3 store との接続・**mock AI（固定テキスト＋時間遅延）による「同時編集テスト」の土台**を作る。実 AI（Rust whisper）を待たずに CRDT 基盤を固める段。

## 背景・課題

- DD-013（親）の最初の一切れ。Yjs は軽量 Rust ラッパーが無く、**フロントのみに配置**する（Rust の SessionState と二重管理しない＝基本設計書の単一所有原則）。
- 日本語プロジェクトでの Yjs 採用事例が少なく、Vue3 binding（y-protocols 等）の選定でつまずきやすい → 小プロトタイプで先行確定する。

## 検討内容

**スコープイン**
- Yjs ライブラリ導入（フロントのみ。`app/` の依存に追加）
- Yjs ドキュメント初期化と Vue3 binding、既存 store への接続
- mock AI（固定テキスト＋遅延）による AI 追記エコーの再現
- CRDT 状態更新の**直列化（single-flight）**強制の枠組み（broadcast channel は採用禁止＝基本設計書 §3.2）
- early action: Node.js REPL＋Yjs で「100字同時書込み」プロトタイプ → binding 選定を先行確定

**スコープアウト（重複回避）**
- 確定タイムラインの清書・要約生成 → DD-012-2 が持つ
- 実 AI（Rust whisper）からの token 流入 → DD-014-4 の統合で扱う
- 確定セグメントの `timeline.push` 採番 → DD-012-1 が Rust 単独で持つ（確定は immutable）
- SQLite 永続化・履歴 → DD-012-3 が持つ

## 決定事項

- Yjs はフロント限定。確定テキストは immutable、CRDT は人間メモ／整形レイヤに限定。
- CRDT 更新は single-flight で直列化（broadcast channel 不使用）。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 各タスクに対象ファイルパスを明記（`app/package.json` 依存追加・`app/src/` の store/SFC）
- [ ] 📐 実装前詳細化トリガー判定（新規依存導入＋並行処理に触れる → **詳細化要の見込み**）
- [ ] 😈 Devil's Advocate（Yjs binding 選定リスク・Vue3 reactivity との結線の罠）

### Phase 1: Yjs 導入と binding 選定（mock AI）
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] Yjs 導入＋ドキュメント初期化＋Vue3 store 結線、mock AI で固定テキスト追記
- [ ] 🔬 機械検証: mock AI 追記と人間キー入力を並行 → store 表示が壊れない／single-flight で直列化されている
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-013 の子・未実装）。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase N DA批判レビュー
（着手時に記録）
