# DD-012-9 Phase 4 実装前詳細化（予定の編集 ／ 議事録の書き出し）

> 親: [DD-012-9](../DD-012-9_S-01カレンダー操作強化_削除と移動ほか.md) Phase 4。**着手前レビュー用**（合意後にコーディング）。
> Phase 3 で S-01 のメニューに「編集」「書き出し」の導線は設置済み（押下＝準備中通知）。本Phaseで実処理を入れる。

## スコープ

- **A. 予定の編集**: S-02 を「編集モード」で開き、既存会議のタイトル/日時/場所/アジェンダ/参加者を直して保存。
- **B. 議事録の書き出し**: 完了議事録(Markdown)を**クリップボードへコピー**（最小・依存なし）。ファイル保存は任意（プラグイン要・下記 D2）。
- ついでに: 空きセル＋からの `/s02?date=YYYY-MM-DD`（Phase 3 で送出済）を S-02 が読んで日付を初期化。

---

## A. 予定の編集（S-02 編集モード）

### 触るファイル
- [S02CreateMeeting.vue](../../../app/src/pages/S02CreateMeeting.vue)（編集モード分岐）
- [S01Calendar.vue](../../../app/src/pages/S01Calendar.vue)（`editMeeting` を準備中通知→ `/s02?id=` 遷移へ）
- BE: [db_commands.rs](../../../app/src-tauri/src/db_commands.rs) `update_meeting` の参加者引数を **任意化**（下記 D1）／[api.ts](../../../app/src/api.ts) `updateMeeting` 署名更新

### データフロー（編集モード）
1. S-01 メニュー「編集」→ `router.push({path:'/s02', query:{id}})`。
2. S-02 `onMounted`: `route.query.id` があれば `getMeetingDetail(id)` を読み、フォームを初期化。
   - `title←meeting.title` / `place←meeting.place` / `agenda←meeting.agenda`
   - `date←scheduled_start[0:10]`（`-`→`/`）/ `start←scheduled_start[11:16]` / `end←scheduled_end[11:16]`
   - `participants ← detail.participants.map(name, role, voice=voice_hint)`
   - 読み込んだ `meeting`（id/status/created_at/final_minutes 等）を保持変数 `editingBase` に退避。
3. 保存ボタンの分岐:
   - **新規**（id 無し）: 従来どおり `createMeeting`（status=scheduled）。
   - **編集**（id 有り）: `editingBase` を土台に編集項目を上書きした `Meeting` を作り、`updateMeeting(meeting, participants?)` を呼ぶ。status・final_minutes・実績時刻・created_at は **そのまま温存**（BE も更新対象外）。
4. 保存後 `/s01` へ。

### フィールド対応・初期化（`?date=` 新規）
- 新規で `route.query.date`（`YYYY-MM-DD`）があれば `date.value = date.replace(/-/g,'/')`、`start/end` は既定（例 10:00/11:00）。

### 決定 D1（編集時の参加者の扱い）★要レビュー
- 問題: Phase 2 の `update_meeting` コマンドは「参加者を全削除→再INSERT」。**完了会議**でこれをやると、タイムラインの話者リンク（`timeline_elements.confirmed_participant_id`、FKは ON DELETE **SET NULL**）が**切れる**。
- 方針（推奨）: コマンドの `participants` を **任意**にする（`Option<Vec<Participant>>`）。
  - `Some(list)` → 従来どおり全入替（**scheduled の編集**で使用）。
  - `None` → 参加者には触れず**会議行だけ更新**（**completed の編集**で使用＝話者リンクを保全。タイトル誤字直し等）。
- UI: completed を編集中は参加者欄を**読み取り専用**にし、保存時 `participants=None` で送る。scheduled は従来どおり編集可＋`Some`。

### エッジ/異常系
- `getMeetingDetail` が null（既に削除済み等）→ 編集不可の通知＋ `/s01` へ。
- 日付の妥当性は既存 `toIso` を流用（不正なら従来のエラー表示）。
- ヘッダ表示（タイトル/バッジ）を編集モードで「会議の編集」に切替。「保存して予約」→「変更を保存」。

### 検証（A）
- vue-tsc。実ウィンドウ: scheduled を編集→保存→S-01 に反映／completed のタイトルだけ編集→保存後も `final_minutes`・話者ラベルが残る（S-03 で確認）。

---

## B. 議事録の書き出し

### 方式の選択肢
- **コピー（推奨・依存なし）**: `navigator.clipboard.writeText(final_minutes)`。Tauri v2 webview は secure context なので動く。新規依存ゼロ。
- **ファイル保存（任意）**: `.md` を保存ダイアログで書き出し。**要追加**: `@tauri-apps/plugin-dialog` + `@tauri-apps/plugin-fs`（JS）、`tauri-plugin-dialog`/`tauri-plugin-fs`（Rust）、capabilities 許可、`lib.rs` 登録。

### 決定 D2（書き出しの範囲）★要レビュー
- **推奨**: Phase 4 は **クリップボードコピーのみ**を実装（即価値・依存ゼロ）。ファイル保存は需要を見てから別タスク（プラグイン導入＋権限設定が必要なため）。

### 置き場所
- S-01 メニュー「書き出し」（completed のみ表示）→ `exportMinutes` を「コピー実行＋Notify(成功/本文なし)」に。
- [S03MinutesDetail.vue](../../../app/src/pages/S03MinutesDetail.vue) 「最終議事録」カードに「コピー」ボタン（設計SSOT §S-03 の“コピー・エクスポート”に対応）。

### 検証（B）
- vue-tsc。実ウィンドウ: completed の「書き出し」→ クリップボードに Markdown が入る（貼り付けで確認）。本文なしは注意通知。

---

## タスク分解（合意後）

### Phase 4a: 予定の編集
- [ ] BE: `db_commands::update_meeting` の `participants` を `Option<Vec<Participant>>` 化（None=会議行のみ更新）。`api.ts` `updateMeeting(meeting, participants?)`。db.rs はそのまま（`update_meeting`/`delete_participants` 既存）。
- [ ] 単体テスト: `participants=None` で参加者・話者リンクが保たれる（completed＋timeline で confirmed_participant_id が残る）ことを追加検証
- [ ] S-02: `?id=` 編集モード（読込・初期化・保存分岐・ヘッダ/ボタン文言・completed は参加者ロック）／`?date=` 初期化
- [ ] S-01: `editMeeting` を `/s02?id=` 遷移に
- [ ] 🔬 vue-tsc＋`cargo test`／😈 DA

### Phase 4b: 書き出し（コピー）
- [ ] S-01 `exportMinutes` を clipboard コピー実装に／S-03 にコピー ボタン
- [ ] 🔬 vue-tsc／実ウィンドウでコピー確認／😈 DA
- [ ] （任意・別判断）ファイル保存: プラグイン導入は D2 で合意できた場合のみ

## 主要な確認事項（レビュー）→ **合意済（2026-06-08）**
1. **D1**: 編集時の参加者 → **採用: scheduledは入替可／completedは参加者ロック＋会議行のみ更新**（話者ラベル保全）。
2. **D2**: 書き出し → **採用: コピーのみ**（ファイル保存は見送り＝依存追加なし）。
3. completed 会議の編集 → **採用: タイトル/日時/場所/アジェンダは編集可・参加者は保護**。

> 実装完了（2026-06-08）: BE `update_meeting` の participants を `Option` 化＋テスト、S-02 編集モード、S-01 編集遷移＋コピー、S-03 コピー。`cargo test` 18 / `vue-tsc` OK。実機E2EはPhase 5。
