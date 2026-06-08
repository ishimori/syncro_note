# DD-016-2: ad-hoc 仮会議のライフサイクル＋保存拡張＋未保存スイープ（案Cの土台）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-09 | 2026-06-09 | 完了 |

> 親: [DD-016](DD-016_S-05リアルタイム画面の改善_録音中の右パネル編集と会話エリア独立スクロールとヘッダ固定.md)。アプローチ: TDD/標準（BE中心・外部I/F追加）。**DD-016-3（右パネル編集UI）の土台**。

## 目的

「今すぐ録音（ad-hoc）」で録音中に追加した**事前資料を清書(S-06)に反映**できるよう（親DD 案C）、ad-hoc 会議をDBに早めに（仮）保存する仕組みと、保存せず離脱した**未保存仮会議を掃除する仕組み**を用意する。

## 背景・課題

- S-05 は「**保存(S-07)するまでDBに会議を作らない**（中断/離脱で幽霊会議を残さない）」設計（DD-012-2）。
- 一方、添付の `add_attachment` は **meeting_id 必須**、かつ添付本文を清書へ統合するには `start_summarize(meetingId)` が会議を参照するため、**会議が清書より前にDBに存在**していなければならない（DD-012-10）。
- ad-hoc には会議行が無いので、案Cでは会議を仮作成する。ただし「幽霊会議を作らない」設計を一部破るため、**掃除（スイープ）が必須**。

## 検討内容

- **仮会議**: `status='active'` ・`final_minutes IS NULL` で作成。`minutesSession.meetingId` に保持し、以降のアジェンダ/参加者/添付は既存のリンク会議と同一経路で永続化。
- **保存(S-07)**: 仮会議が有る場合は `complete_meeting` で確定（agenda・participants も書き戻すよう拡張）。これまで `complete_meeting` は linked 予定向けで本体のみ更新だったため、**agenda・participants を引数追加**し、ad-hoc/linked 双方で破綻しないようにする（linked の既存話者リンク保全に注意）。
- **掃除**: ①アプリ起動時スイープ（`status='active' AND final_minutes IS NULL` を削除＝CASCADEで参加者/添付/タイムラインも消える）。②保存せず S-05/S-06 を離脱したときの明示削除（DD-016-3 側で呼ぶ削除コマンド）。③カレンダー(S-01)一覧から未保存仮会議を除外。
- 既存 `delete_meeting`（CASCADE）を離脱時削除に流用できるか確認（流用可ならコマンド追加不要）。

## 決定事項

- 仮会議は `status='active'`／`final_minutes IS NULL` を「未保存」の印として扱う（既存スキーマ変更なし）。
- スイープは**起動時**＋**離脱時削除**の二段構え（起動時が取りこぼしの最終防衛線）。

## タスク一覧

### Phase 1: 実装
- [ ] 📐 **実装前詳細化** → 👀 レビュー（コマンドのシグネチャ／SQL／掃除条件／complete_meeting 拡張の before/after／linked への影響）
- [ ] 🧪 **テストシナリオ作成・👀合意**（仮会議作成→添付→保存で completed 化／保存せず離脱で消える／起動時スイープ／linked 会議は影響なし）
- [x] **方針確定（最小実装）**: ad-hoc 仮会議の作成は既存 `create_meeting`（status='active'・scheduled_end=NULL）を、保存は既存 `update_meeting`＋`complete_meeting` を、中断削除は既存 `delete_meeting` を**再利用**。→ **新コマンド・complete_meeting 拡張・api.ts 変更は不要**と判明（呼び出しは DD-016-3 の FE 側で行う）。
- [x] `app/src-tauri/src/db.rs`: `delete_unsaved_adhoc_meetings`（`status='active' AND final_minutes IS NULL AND scheduled_end IS NULL` を削除＝CASCADE）を追加
- [x] `app/src-tauri/src/db.rs`: `list_meetings_by_month` に同条件の `NOT (...)` 除外を追加（カレンダーに未保存仮会議を出さない）
- [x] `app/src-tauri/src/lib.rs`: `setup()` 起動時にスイープを実行（失敗はログのみ）
- [x] 🔬 **機械検証**: `cargo test --lib db::` → **25 passed / 0 failed**（新規 `sweep_deletes_only_unsaved_adhoc_meetings` 含む。既存のシード分布・月次一覧テストも無傷）
- [x] 😈 **DA批判レビュー**: 下記

## ログ

### 2026-06-09
- 親DD-016から分割して作成（案Cの土台＝BE）。
- 実装: 既存コマンド再利用に倒し BE 追加を最小化（db.rs にスイープ＋一覧除外、lib.rs に起動時スイープ）。`status='active'` がシードのデモ会議でも使われる衝突を回避するため、判別条件に **`scheduled_end IS NULL`**（予定でない＝ad-hoc 仮会議）を加えた。cargo test 25件パス。レビューなし一括方針につきユーザーレビューは省略。

---

## DA批判レビュー記録

<!-- 手順・品質フィルターは doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー

**DA観点:** 仮会議の幽霊化・掃除の誤削除で最も壊れやすい点は？

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | スイープ条件を `status='active' AND final_minutes IS NULL` だけにすると、シード/予定由来の active 会議（例「本日の定例」）まで誤削除する | 高 | 当月カレンダーを開く（dev でシード投入）→ 起動時スイープで「本日の定例」が消える | データ破壊（誤削除） | ✅修正済（`scheduled_end IS NULL` を条件に追加。テストで active+scheduled_end ありが残ることを保証） |
| 2 | 録音中（保存前）の仮会議がカレンダーに「未完了の会議」として出てしまう | 中 | ad-hoc 録音開始→資料追加で仮会議作成→カレンダーへ | 中途半端な可視状態 | ✅修正済（`list_meetings_by_month` で同条件を除外） |
| 3 | アプリ再起動が録音中に起きると仮会議が掃除される | 低 | 録音中にアプリ再起動 | 想定外の消失 | ❌不要（録音状態は元々メモリ上で再起動時に失われる。許容） |
