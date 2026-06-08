# DD-013-1: Yjs 導入と Vue3 バインディング基盤（mock AI で同時編集の土台）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 完了（実装＋Playwright機械検証済・2ペイン同時編集の非破壊を確認） |

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
- [x] 📋 対象ファイル明記: 依存=`app/package.json`(yjs追加) / 新規=`app/src/crdt/memoDoc.ts`・`app/src/crdt/mockAi.ts` / 改修=`app/src/pages/S05Realtime.vue`
- [x] 📐 実装前詳細化トリガー判定（新規依存＋並行処理）→ 該当。方針を実装に内包（Y.Text＋最小差分＋single-flight=`doc.transact`、broadcast不使用）。ユーザーは「お任せ」方針のため形式レビューは省略
- [x] 😈 Devil's Advocate（下記DA記録）

### Phase 1: Yjs 導入と binding 選定（mock AI）
- [x] 📐 実装方針確定: Vue3結線は y-* binding を使わず `Y.Text.observe`↔`ref` の薄い自前結線（日本語事例不足の罠を回避）
- [x] Yjs 導入＋ドキュメント初期化＋Vue3 結線、mock AI（dev・Tauri不要）で固定テキスト追記
- [x] 🔬 機械検証(Playwright): 模擬AIが左へ31件自動追記中に人間が右メモへ32字入力 → メモ完全無傷（`重要メモ:予算は来週確定、担当はAさん。来週月曜までに見積もり。`）・表示崩れなし。single-flight=`doc.transact`で直列化
- [x] 😈 DA批判レビュー（下記）

## ログ

### 2026-06-08（起票）
- 起票（DD-013 の子・未実装）。

### 2026-06-08（実装・検証・完了）
- `yjs` 導入。`app/src/crdt/memoDoc.ts`（Y.Doc/Y.Text＋`MemoProvider`抽象＋`applyMinimalEdit`最小差分＋single-flight＋`useMemoDoc`結線）と `mockAi.ts`（dev模擬AI）を新規作成。
- `S05Realtime.vue` を2ペイン化（左=AI確定タイムライン[immutable]／右=同時編集メモ[CRDT]）。人間メモを footer 単一行から CRDT テキスト域へ移行。保存パス（`buildTranscript`／`minutesSession.timeline`）は human_memo 行として温存。
- 検証: `vue-tsc --noEmit` 型OK。Playwright(:1420・Tauri無)で模擬AI31件追記中の人間メモ32字入力が無傷。エビデンス: 同時編集中スクショ取得。
- 実機確認(CDP・2026-06-08): 実ウィンドウで実STT(サンプル12件)→メモ入力＋左→右コピー→「会議を終了」まで通し、コンポーネントと同一の `session` モジュールを直読みして `minutesSession.timeline`=AI12行＋human_memo2行、transcript末尾に【メモ】2行を確認（memo→human_memo 反映OK）。保存(S-07)のDB書込みは DD-012 の未変更コードのため、実DB汚染回避で意図的に未実施。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー（2026-06-08）

| # | 指摘 | 重要度 | 対応 |
|---|------|--------|------|
| 1 | textarea を v-model 全置換すると別位置の並行挿入を破壊する（broadcast相当・基本設計書§3.2違反） | 高 | `applyMinimalEdit` が前方/後方一致を保ち中央差分のみ delete+insert。DD-013-2 のVitestで別位置の並行編集が両方残ることを確認済 |
| 2 | `observe→ref→textarea` 再代入の自己ループ／カーソル飛び | 中 | 変更は `doc.transact` に集約し `LOCAL_ORIGIN` で識別。単独クライアントではカーソル維持。複数人時のカーソル保持は将来課題として明記 |
