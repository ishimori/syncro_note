# DD-011: Phase4 Tauri 2ペインUI骨格 — Python中身に接続

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-08 | 進行中（Phase 3 完了。次=Phase 4 or 別DD） |

> アプローチ: 標準（探索的実装）。画面の「見た目の合意」は DD-009（[doc/spec/画面設計書.md](../spec/画面設計書.md)）＋ HTMLモック（[doc/mock/html/](../mock/html/)）で確定済みのため、本DDは**雛形作成＋中身（Python）との疎通**という振る舞い中心の作業。

## 進捗サマリ（2026-06-08 更新）

| Phase | 状態 | 成果物 |
|-------|------|--------|
| Phase 0 事前精査 | ✅完了 | 詳細化判定（P1/P3=要）・DA 5件（最重要=配布時Python同梱→別DD） |
| Phase 1 Tauri+Quasar雛形 | ✅完了 | `app/`（Tauri2+Vue+TS+Quasar）。ウィンドウ起動・ボタン操作までユーザー目視OK |
| Phase 2 画面骨格（静的） | ✅完了→**全8画面へ拡張** | 当初S-05のみ→**S-01〜S-08の全画面＋共有ナビ＋ルーター**へ拡張（下記 Phase 3-A で確定）。`app/src/pages/S0*.vue`／`components/AppNav.vue`／`router/index.ts` |
| **Phase 3 Python中身に接続** | ✅**完了**（3-A/3-B/3-C 全完了） | 工程が多いため 3-A/3-B/3-C に分割（下記「Phase 3」節）。**3-A/3-B/3-C すべて✅完了**。実ウィンドウで「サンプルを流す」→ 左タイムラインに文字起こしが1行ずつ表示、閉じると裏方プロセス残存なしまで実測確認 |

**Phase 3 の3分割（2026-06-08 再編・ユーザー合意）**:
- **3-A 全画面シェル確定** … ✅**完了**。S-01〜S-08の静的骨格＋共有ナビ（`AppNav`・WIPバッジ・現在地ハイライト）＋`vue-router`（ハッシュ履歴）を確定。`npm run dev`(vite)配信＋**Playwrightで全8画面を目視確認**（静的＝Playwright可）。証跡 `DD-011/phase3a-s0*.png`。補助スクリプト `scripts/{start,stop,build}-app.sh` も追加。
- **3-B Python実行口** … ✅**完了**。`sidecar.py` を追加し、`uv run` で **JSON Lines 逐次出力を CLI 単体確認**（sample01.wav→meta1+segment12+done1、全行JSON・seq連番・count一致／異常系=error行＋exit1／ruff通過）。
- **3-C Rust中継＋S-05ライブ配線** … ✅**完了**。Rust `start_transcription` で sidecar を spawn＋stdout を reader スレッドで1行ずつ読み `stt-meta/segment/done/error` を emit＋`Child` 保持でウィンドウ破棄時に **taskkill /T でツリーごと kill**（DA-新4を実装で解消）。フロント S-05 は4イベントを listen→`timeline.push`、開始ボタン／準備中スピナー／mm:ss／ダミー撤去。**実ウィンドウで実測**：「サンプルを流す」→ meta+segment×11+done が1行ずつ左タイムラインに表示（日本語化けなし）→「完了（11件）」。閉じると taskkill ツリーkillが発火し uv/python 残存なし（exit 0・実測）。

> 3-B/3-C の📐実装前詳細化は [DD-011/Phase3_実装前詳細化.md](DD-011/Phase3_実装前詳細化.md)（全体）＋ [DD-011/Phase3C_実装前詳細化.md](DD-011/Phase3C_実装前詳細化.md)（3-C限定の確定API・検証手段）。Phase 0 DA #1〜4（配布時同梱は別DD／UTF-8／unbuffered／子プロセスkill）を織り込み済み。**Phase 3 完了**。

> 確立した運用: **UIの目視確認は Playwright で `localhost:1420` を開いてClaude自身が行う**（CLAUDE.md「UI確認」節／メモリ `tauri-ui-verify-playwright`）。

## 目的

企画書の最終形「製品の皮」（Phase 4）の**最初の一切れ**を作る。具体的には:

1. **Tauri + Quasar の雛形**が起動する（OS標準WebViewで動くデスクトップアプリの枠）。
2. 中核画面 **S-05** の骨格を表示する。※ロードマップの旧称「左=AI/右=人間メモの2ペイン」は古く、**設計SSOT（DD-009＋モック）では「確定文字起こしのタイムライン（主役）＋人間メモを時系列に混在、右はコンテキスト・ドロワー、下はメモ入力」**に進化済み。本DDはSSOTに忠実に作る。
3. 既存の **Python中身（`synchroni_note` の文字起こし）と疎通**し、文字起こし結果を**タイムラインへ逐次流せる**。

> ロードマップ P4-1「画面が表示され、AI側へテキストを流せる」に対応。**同時編集(Yjs/CRDT)＝P4-2、ホットパスRust移植＝P4-3 は本DDの対象外**（後続DD）。リアルタイムのマイク収音も範囲外（まずはサンプル音声ファイルでの疎通で「中身↔皮」の経路を成立させる）。

## 背景・課題

- 中身（録音→文字起こし→要約）は Python で動作実証済み（DD-008/010）。設計図も DD-009 で凍結済み。**残るは「製品の皮（配布できるデスクトップアプリのUI）」**で、これが Phase 4。
- 実会議音声がまだ入手できず、文字起こし/要約の最終品質評価（実会議での検証）は保留中。一方 **2ペインUIは話者識別の有無に依存しない**ため、品質評価を待たずに皮の着手が可能（DD-004/006 は別セッションで並行進行中）。
- Phase 4 は Tauri/Web/Rust/CRDT という新スタックが乗る最もリスクの高い工程。**一度に全部やらず**、まず「皮が起動し、Pythonの中身と会話できる」最小経路を通すのが本DDの狙い（助走）。

## 検討内容

### 技術スタック（DD-009・ロードマップ§7で既定）

- シェル: **Tauri**（Rust）。フロント: **Quasar（Vue 3 + TypeScript）**。モックが Quasar コンポーネント前提で作られている（DD-009 §4 コンポーネント・インベントリ）。
- 環境前提（2026-06-07 実機確認済）: Node v22.20 / npm 10.9 / Rust(cargo) 1.94。**Tauri CLI のみ未導入**（雛形作成時に導入）。

### 中身（Python）と皮（Tauri）の接続方式 — 本DDの肝

| 案 | 内容 | 評価 |
|----|------|------|
| **A: Pythonサイドカー（採用）** | Tauri(Rust)側が Python パイプラインを子プロセスとして起動し、**標準出力の JSON Lines（1行＝1文字起こしセグメント）**を読んで Tauri イベントでフロントへ中継 | ✅ 完全オフライン・単一アプリ起動の思想（§7.1）に合う。ユーザーがサーバを別途立てる必要なし。製品期もこの境界を維持しやすい |
| B: localhost HTTP サーバ | Python を FastAPI 等で常駐させフロントが叩く | ❌ §7.1 で否定した「サーバ＋ブラウザ」型に逆戻り。常駐・ポート管理が増える |
| C: 今すぐ Rust 移植 | whisper-rs へ置換 | ❌ ロードマップ上 Rust移植は P4-3（最後）。中身の作り直しは時期尚早 |

→ **案A（Pythonサイドカー / stdout JSON Lines → Tauriイベント）**。本DDでは Python 側に「セグメントを JSON Lines で吐く薄い実行口」を1つ足し、Rust 側でそれを spawn して中継する。

### スコープの絞り（最小の一切れ）

- 入力は**サンプル音声ファイル**（マイク収音=後続）。既存 `stream_transcribe`（[python/src/synchroni_note/pipeline/transcribe.py](../../python/src/synchroni_note/pipeline/transcribe.py) 系）の逐次出力をそのまま流用。
- 右ペイン（人間メモ）は**ローカル編集できるテキスト領域のみ**（保存・CRDTは範囲外）。
- 要約・話者ラベル・DB保存・状態遷移は**範囲外**（左ペインに文字起こしが流れることを最優先）。

## 決定事項

- スタック = **Tauri + Quasar(Vue3/TS)**。配置 = リポジトリ直下に新規 `app/`（または `desktop/`）。**Phase 1 の📐詳細化でディレクトリ名を確定**。
- 接続方式 = **案A: Python サイドカー（stdout JSON Lines → Tauri イベント中継）**。
- 最小スコープ = 「**雛形起動 → S-05の2ペイン骨格表示 → サンプル音声の文字起こしが左ペインへ逐次表示**」。Yjs/マイク/要約/保存は後続DD。

## Phase 1 実装前詳細化（📐 / 👀 レビュー用）

> 「アプリの枠をどこに・どの手順で作るか」の具体化。**この章の合意後に Phase 1 のコーディングを開始**する。

### 配置と共存

- **出典＝[DD-001](DD-001_環境初期化_uvプロジェクト雛形とruff_pytest.md)**（案B採用: Python=`python/` / Tauri=`app/`、`app/src`=フロント・`app/src-tauri`=Rust）。本DDはこの既定構造に従う。
  - ※DD-001 はフロントを走り書きで「TS/React/Yjs」と記したが、UIフレームワークは後発の **DD-009・ロードマップ§7 で Quasar(Vue) に確定**（モックもQuasar）。本DDは新しい決定（Quasar/Vue）に従う。
- リポジトリ直下に **`app/`** を新規作成（既存 `python/` と並ぶ独立フォルダ。相互にビルド依存なし）。
  ```
  c:\repo\syncro_note\
  ├── python/        # 既存（中身＝文字起こし・要約）
  ├── app/           # 新規（皮＝Tauri+Quasar）
  │   ├── src/           # Vue3+TS フロント（Quasar UI）
  │   └── src-tauri/     # Rust シェル
  └── doc/ …
  ```
- `.gitignore` に追記: `app/node_modules/` ・ `app/src-tauri/target/` ・ `app/dist/`（ビルド生成物はコミットしない）。

### scaffold 手順（確定）

DA#5 の通り **Quasar CLI の Tauri モードは存在しない**ため、「**Tauri(Vue+TS+Vite)雛形 ＋ Quasar を Viteプラグインで載せる**」構成にする。

1. `npm create tauri-app@latest` → project=`app` / frontend=**TypeScript** / framework=**Vue** / package manager=**npm**（Tauri 2系）。
2. `cd app && npm install` → 雛形が `npm run tauri dev` で空ウィンドウ起動することを確認。
3. Quasar を Vite プラグインとして追加:
   - `npm install quasar @quasar/extras` ／ `npm install -D @quasar/vite-plugin sass-embedded`
   - `vite.config.ts` に `@quasar/vite-plugin` を追加（`transformAssetUrls` 込み）。
   - `src/main.ts` で `app.use(Quasar)`、Quasar の CSS / Material アイコンを import。
4. 動作確認用に `App.vue` へ Quasar コンポーネント（`<q-btn>` 1つ）を置き、Quasar が効いていることを目視。

### Windows 前提（確認済/留意）

- WebView2：Windows 11 に同梱済（追加導入不要）。Rust(cargo) 1.94 導入済。Node v22.20／npm 10.9 導入済。
- Tauri CLI は手順1で devDependency として入る（グローバル導入は不要）。

### Phase 1 完了条件（DoD）

- `cd app && npm run tauri dev` で**デスクトップウィンドウが起動**し、**Quasarのボタンが描画**される（＝Tauri＋Quasar が結線できている）。スクショを `DD-011/` に保存。

### この設計のリスク（Phase 1 DA 先出し）

- create-tauri-app の対話/テンプレ名はバージョンで変わりうる → 実行時の選択肢に合わせて読み替える（フレームワーク=Vue, 言語=TS が取れれば可）。
- Quasar の Vite プラグイン導入は `sass-embedded` 必須 → 入れ忘れるとビルド失敗。手順3に明記済。

## タスク一覧

### Phase 0: 事前精査 ✅
- [x] 📋 **各Phaseのタスク精査・詳細化**（対象パス明記・🔬機械検証の有無）
- [x] 📐 **実装前詳細化トリガー判定**
  - 規模シグナル: ☑ 新規モジュール（`app/` 一式）追加 ／ ☑ 新規外部I/F（Python↔Tauri のサイドカー契約＝JSON Lines スキーマ）／ ☑ 3ファイル以上
  - 複雑度シグナル: ☑ 並行処理（子プロセスの stdout を読みつつUIへ中継）
  - 判定結果: **Phase 1・3 → 詳細化要**（着手前に 📐＋👀ユーザーレビュー）。Phase 2（モック準拠の静的UI）→ 詳細化不要
- [x] 😈 **Devil's Advocate調査** → [Phase 0 DA批判レビュー](#phase-0-da批判レビュー)に5件記録。最重要は**配布時のPython同梱コスト**（本DDの開発時は `uv run` 直叩きで回避し、製品ビルド時の同梱は後続DDに分離）

### Phase 1: Tauri + Quasar 雛形（📐詳細化要 → 👀レビュー後に着手）
- [x] 📐 **実装前詳細化** → [Phase 1 実装前詳細化](#phase-1-実装前詳細化-📐--👀-レビュー用)に記載。👀 ユーザーレビュー（`app/` 配置・出典DD-001 を確認・合意）
- [x] `app/` に Tauri 2 + Vue + TS 雛形を scaffold（`npm create tauri-app`）。`npm install` 完了
- [x] Quasar を Viteプラグインで搭載（`vite.config.ts` に `quasar()`／`main.ts` で `app.use(Quasar)`＋プリビルドCSS）。`npm run build` 成功（vue-tsc 通過・QuasarのCSS組込み確認）
- [x] 🔬 **機械検証**: `npm run tauri dev` → Rustコンパイル成功（`Finished dev ... 2m21s` → `Running target\debug\app.exe`）、**デスクトップウィンドウ起動**
- [x] 😈 **DA批判レビュー** → [Phase 1 DA批判レビュー](#phase-1-da批判レビュー)に記録（初回 q-page を q-layout なしで使い**画面真っ白**＝Quasar例外。レイアウト非依存の最小構成に修正しHMR反映で復旧）

### Phase 2: S-05 画面骨格（静的）✅
- [x] [doc/mock/html/S-05_realtime.html](../mock/html/S-05_realtime.html) を Quasar SFC 化 → `app/src/pages/S05Realtime.vue`（`q-layout`→ヘッダ/左ナビdrawer/右コンテキストdrawer/`q-page-container`タイムライン/フッターメモ入力）。`App.vue` がホスト＋ブランド色（インディゴ/ティール）適用
- [x] 確定タイムライン（話者バッジ・整形追い上げ・unrefinedバッジ）＋人間メモ（chat風）＋生成中チャンク（spinner）を表示。ローカル操作（話者割当 `assign`／メモ投入 `sendMemo`／整形トグル）動作
- [x] 🔬 **機械検証**: `npm run build` 成功（vue-tsc 通過・120 modules）＋ `npm run tauri dev` で**S-05画面が起動表示**（ユーザー目視OK・スクショ確認）
- [x] 😈 **DA批判レビュー** → [Phase 2 DA批判レビュー](#phase-2-da批判レビュー)（①停止後にvite子プロセスが残りポート1420占有＝DA#4の実例 ②右drawerが overlay で主役を暗転→`show-if-above`で解消）

### Phase 3: Python中身に接続 — 3分割（3-A/3-B/3-C）

> 工程が多いため3分割（2026-06-08 再編・ユーザー合意）。**3-A=完成済みシェルの確定（静的・Playwright可）／3-B=Python実行口（CLI単体確認・Tauri不要）／3-C=Rust中継＋ライブ配線（実ウィンドウ確認）**。境界は「アプリ無しで単体確認できるか」で切っている。

#### Phase 3-A: 全画面シェル確定（静的・ナビ／ルーター）✅
- [x] S-01〜S-08 の静的骨格を実装（モック忠実、`app/src/pages/S0*.vue`）。※当初Phase 2のS-05のみから**全画面へ拡張**
- [x] 共有ナビ `components/AppNav.vue`（WIPバッジ・現在画面ハイライト）＋ `vue-router`（ハッシュ履歴 `router/index.ts`）で画面遷移
- [x] 補助スクリプト `scripts/{start,stop,build}-app.sh`（ポート1420の後始末を含む＝DA#4の当面運用）
- [x] 🔬 **機械検証**: `npm run build`（vue-tsc 通過・179 modules）成功
- [x] 👁 **目視確認**: `npm run dev`(vite)配信＋Playwrightで**全8画面**を確認（静的のためPlaywright可）。崩れ・破綻なし。証跡 `DD-011/phase3a-s01〜s08.png`
- [x] 😈 **DA批判レビュー** → [Phase 3-A DA批判レビュー](#phase-3-a-da批判レビュー)

#### Phase 3-B: Python実行口（サイドカー）✅
- [x] `python/src/synchroni_note/pipeline/sidecar.py` を追加（既存 `stream_transcribe` を **JSON Lines で逐次stdout**。`sys.stdout` をUTF-8化＋各行 `flush`＝DA#2/#3。stdoutはJSON専用・ログ/トレースはstderr＝DA-新3）。ruff check/format 通過
- [x] 🔬 **機械検証（正常系）**: `uv run python -m synchroni_note.pipeline.sidecar audio/sample01.wav --model base` → `meta`(duration_s=70.0)→`segment`×12（seq0..11・日本語化けなし）→`done`(count=12, elapsed_s≈4.4) が**1行ずつ**。自動検証で「全行JSON・seq連番・count一致」を確認
- [x] 🔬 **機械検証（異常系）**: 存在しないwav→`error`行1つ＋**exit 1**、トレースはstderr（stdout汚染なし）
- [x] 😈 **DA批判レビュー** → [Phase 3-B DA批判レビュー](#phase-3-b-da批判レビュー)

#### Phase 3-C: Rust中継＋S-05ライブ配線（実ウィンドウ）✅
> **設計入力（Phase 2 コードレビュー由来・厳選／3-Cで反映）**: ①**タイムラインは `q-virtual-scroll`**（長時間会議で数千件→全DOM常駐はCPU負担。本機はCPUのみでSTT/LLMとCPUを食い合う）②**話者割当メニューは行ごとでなく共有1個**③**v-forのkeyはバックエンド採番の安定IDを使う**（末尾追加だけなら現状の index key でも実害ないが、時刻順挿入/後追い整形が入ると壊れる）。その他の指摘（deep reactive→shallow化, displayName毎回呼び, CSS/アイコン全読み, デモ時刻のslice 等）は時期尚早/難癖/使い捨てデモのため**対応不要**。
> **注**: ①〜③（virtual-scroll/共有メニュー/安定ID）は本3-Cでは**未対応のまま見送り**（疎通優先・本DD範囲外）。実会議の長時間データを積む段で対応する別DD候補として残す。本3-Cは「経路が通ること」を最優先（DoD通り）。
- [x] Rust(Tauri): `start_transcription` で sidecar を **spawn**、stdout を reader スレッドで1行ずつ読んで `stt-meta/segment/done/error` で **emit**（各 emit に `eprintln!` 検証ログ）、`Child` 保持でウィンドウ破棄時に **taskkill /T でツリーごと kill**（DA#4・新4＝実装で解消）。`uv` は `CREATE_NO_WINDOW`＋`current_dir(<repo>/python)`＋`PYTHONUTF8=1`。[app/src-tauri/src/lib.rs](../../app/src-tauri/src/lib.rs)
- [x] フロント(S-05): 4イベントを `listen`→`timeline.push`、**開始ボタン**「サンプルを流す」追加、**準備中スピナー**（meta受信まで＝DA-新1）／mm:ss整形／完了・エラー表示、ダミー4件＋生成中チャンクを**撤去**、素ブラウザ(Tauri不在)はボタン無効化。[app/src/pages/S05Realtime.vue](../../app/src/pages/S05Realtime.vue)
- [x] 🔬 **機械検証**: 実ウィンドウで「サンプルを流す」→ Rustコンソールに `[stt] emit stt-meta`→`stt-segment`×11→`stt-done`→`stdout closed`、S-05左タイムラインに **meta+11件が1行ずつ**表示（日本語化けなし・mm:ss・unrefinedバッジ・完了11件）。ウィンドウを閉じる→`taskkill tree pid=… -> exit code: 0` 発火、**uv/python 残存なし**を実測（mid-flightクローズでも孫reap）。証跡 `DD-011/phase3c-*.png`
- [x] 😈 **DA批判レビュー** → [Phase 3-C DA批判レビュー](#phase-3-c-da批判レビュー)

## ログ

### 2026-06-08
- **Phase 3-C 完了（Rust中継＋S-05ライブ配線・実ウィンドウ実測）＝Phase 3 全完了**。Rust `start_transcription` が `uv run python -m …sidecar` を spawn し、stdout を reader スレッドで1行ずつ読んで `stt-meta/segment/done/error` を emit、フロント S-05 が listen→`timeline.push`。**実ウィンドウで実測**：「サンプルを流す」→ `[stt] emit stt-meta`→`stt-segment`×11→`stt-done`がコンソールに出、左タイムラインに meta+11件が1行ずつ表示（日本語化けなし／mm:ss／unrefinedバッジ／「完了（11件）」／準備中スピナー）。ダミー4件＋生成中チャンクは撤去。**後始末**：ウィンドウを閉じると `kill_sidecar` が発火、`child.kill()`（uvのみ）では孫pythonが残る恐れ（DA-新4）→ **`taskkill /T /F /PID` でプロセスツリーごとkill** に格上げし、mid-flightクローズでも uv/python 残存なし（exit 0）を実測。**検証手段の確立**：Playwright不可のため `scripts/{shot-window,click,uia}.ps1` を新設（AttachThreadInputで前面化→画面矩形を実ピクセルキャプチャ＝WebView2のGPU合成でも空白にならない／座標クリック）。既定ウィンドウが 800×600 で左ナビが折りたたみ＆狭い→ `tauri.conf.json` を **1200×800・center** に拡大（§6の指摘を実装）。次=Phase 4(同時編集/Rust移植)系は後続DD、マイク収音・話者分離・LLM整形・配布時Python同梱も各別DD。DA(3-C)→ [Phase 3-C DA批判レビュー](#phase-3-c-da批判レビュー)。
- **異常終了からの復旧 ＋ Phase 3 を3分割に再編**。前回セッションが Phase 3 着手前後で異常終了。調査の結果、中断時の作業は設計書（サイドカー）とは別の「**全画面シェル化**」で、**コードは完成しビルドも通る**状態だった（未確認・未コミット）。成果＝S-01〜S-08の静的骨格＋共有ナビ(`AppNav`)＋`vue-router`＋補助スクリプト3本。設計書（[Phase3_実装前詳細化.md](DD-011/Phase3_実装前詳細化.md)）＝サイドカーは未着手のまま（=新3-B/3-C）。
- **Phase 3-A 完了**。`npm run dev`(vite)配信＋Playwrightで**全8画面を目視確認**（静的のためPlaywright可。Tauriランタイム依存部は無し）。崩れ・破綻なし、ナビの現在地ハイライトも反応＝ルーター結線OK。証跡 `DD-011/phase3a-s01〜s08.png`。工程が多いため Phase 3 を **3-A（画面シェル確定）/3-B（Python実行口・CLI確認）/3-C（Rust中継＋ライブ配線・実ウィンドウ）** に再編（ユーザー合意）。次回入口＝3-B。
- **DA（3-A）2件**: ①各画面が自前の `leftDrawer`＋`<AppNav>` を持つため、ドロワー開閉状態が画面遷移でリセット（desktopは `show-if-above` 常時表示で実害ほぼ無し）②8画面で `q-layout`/ヘッダ雛形が重複（将来の共有レイアウト化候補）。＋③モック固定値（「今日=7日」等）の陳腐化は3-C以降の実データ接続で撤去。いずれも低優先で記録のみ。詳細は[Phase 3-A DA批判レビュー](#phase-3-a-da批判レビュー)。
- **Phase 3-B 完了**。Python実行口 `sidecar.py` を追加（既存 `stream_transcribe` を JSON Lines で逐次stdout、UTF-8/各行flush、stdout=JSON専用・ログ/トレース=stderr）。`uv run ... audio/sample01.wav --model base` で **meta→segment×12→done が1行ずつ**・全行JSON・seq連番・count一致を自動検証。異常系=`error`行＋exit1も確認。ruff通過。**次=3-C（Rust中継＋S-05ライブ配線・実ウィンドウ）**。DA(3-B)2件: ①`meta`はモデル読込＋音声decode後に出る＝medium初回は数〜数十秒の"準備中"が続く（DA-新1の実体／3-Cでスピナーに集約）②whisperスレッド数がコード既定8と設定モック(4)で不一致＝設定連携時に統一。詳細は[Phase 3-B DA批判レビュー](#phase-3-b-da批判レビュー)。

### 2026-06-07
- **Phase 0 実施**。詳細化トリガー判定（Phase 1・3=詳細化要）。DA 5件記録（最重要=製品配布時のPython同梱→別DD分離。Windows文字化け/バッファリング/ゾンビプロセス/Quasar非公式モードは各Phase詳細化で対応）。
- **Phase 1 詳細設計（📐）作成**。配置=ルート直下 `app/`、scaffold=「Tauri(Vue+TS+Vite)雛形＋QuasarをViteプラグインで搭載」に確定。フォルダ構造の出典が **DD-001（案B: python/＋app/）** と確認でき、ユーザー合意。
- **UI確認ワークフロー確立（重要）**。`tauri dev` 配信中の `http://localhost:1420` を **Playwright MCP で開き Claude 自身がスクショ→Read で目視確認**できることを実証（ユーザーのスクショ依頼が不要に）。CLAUDE.md「UI確認」節＋自動メモリ `tauri-ui-verify-playwright` に永続化。証跡: [DD-011/s05-phase2-after.png](DD-011/s05-phase2-after.png)（右drawerドッキング後）。制約=Tauriランタイム依存部は素ブラウザで動かない。
- **Phase 2 実装・完了**。S-05 を `app/src/pages/S05Realtime.vue` に SFC 化（モック忠実）。`App.vue` がホスト＋ブランド色。`npm run build`（vue-tsc 通過）→`tauri dev` で S-05 起動表示、ユーザー目視OK。DA 2件（①停止後vite残存でポート1420占有＝DA#4実例→当面killして再起動／③右drawer暗転→`show-if-above`）。S-05の正しい姿は「2ペイン」でなく確定タイムライン主役＋メモ＋右コンテキスト（目的を訂正）。
- **Phase 1 実装・完了**。`app/` に Tauri2+Vue+TS 雛形作成→Quasar搭載→`npm run build` 成功→`npm run tauri dev` でRustコンパイルOK（2m21s）・ウィンドウ起動。初回は `q-page` を `q-layout` なしで使い画面真っ白（DA#1）→レイアウト非依存の最小構成へ修正しHMRで復旧。**ユーザー目視確認OK**（見出し・サブタイトル・青Quasarボタン表示、ボタンのクリックでカウント増加＝Quasarのインタラクションも動作。手動キャプチャ＝チャット添付で確認）。dev/monitor プロセスは確認後に停止。Phase 1 の DoD 達成。次は Phase 2（S-05 2ペイン骨格）。
- DD作成。Phase 4（製品の皮）の最初の一切れとして起票。DD-004/006 が別セッションで並行進行中のため、本セッションは2ペインUI骨格（話者識別非依存）に着手。実会議音声が未入手で品質評価が保留のため「皮を先に、チューニングは後」の順で進める判断（ユーザー合意）。接続方式は Python サイドカー（案A）を採用。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 0 DA批判レビュー

**DA観点:** （サイドカー方式の落とし穴／新スタック導入の後戻りリスク／Windows特有の罠）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **製品配布時の Python 同梱**: 最終 `.msi` に Python ランタイム＋whisper等を同梱する必要があり重く・複雑（PyInstaller等）。今これを設計に持ち込むと一切れが膨らむ | 高 | 製品ビルドで `uv` 前提のままだと配布物が動かない | 後戻り/スコープ肥大 | ⏭️**別DDに分離**。本DDの開発時は `uv run` 直叩きで疎通のみ確認。サイドカー契約(JSON Lines)を挟むので、後で同梱exeに差し替えても契約は不変 |
| 2 | **Windowsの文字化け**: Python stdout 既定が cp932 で、日本語文字起こしが化ける/例外 | 高 | サイドカーをそのまま起動→左ペインが文字化け | Windows特有 | ✅Phase 3詳細化で対応: Python側 `PYTHONUTF8=1`＋`sys.stdout` を UTF-8/line-buffered、Rust側も UTF-8 で読む |
| 3 | **stdout バッファリングで逐次にならない**: Python が出力をため込み、文字起こしが最後に一気に出る（「逐次表示」が成立しない） | 高 | セグメントが1件ずつ来ず末尾でまとめて表示 | サイドカー方式の罠 | ✅Phase 3詳細化で対応: `python -u`（unbuffered）＋各行 `flush=True`＋1行=1 JSON |
| 4 | **子プロセスが残る（ゾンビ）**: ウィンドウを閉じてもPythonが生き続けCPU/メモリ占有 | 中 | アプリ終了後もタスクマネージャに python/whisper が残る | プロセス寿命 | ✅Phase 3詳細化で対応: Rust側でウィンドウ破棄時に子プロセスを kill。Tauri の Command/CommandChild を保持して終了時に確実に殺す |
| 5 | **Quasar は Tauri 公式モードでない**: Quasar CLI の mode に Tauri は無く、scaffold手順を誤ると詰む | 中 | `quasar mode add tauri` を探して存在せず手戻り | 新スタックの落とし穴 | ✅Phase 1詳細化で対応: 「Tauri(Vue+TS+Vite)雛形 ＋ Quasar を Viteプラグイン(`@quasar/vite-plugin`)で載せる」構成に確定（Quasar CLI mode は使わない） |

### Phase 1 DA批判レビュー

**DA観点:** （Quasar導入の落とし穴／雛形の前提崩れ）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **`q-page`/`q-page-container` を `q-layout` なしで使うと画面全体が真っ白**（Quasarが「QPageはQLayoutの子が必須」と実行時例外→Vueマウント失敗）。`npm run build`・Rustコンパイルは通るため気付きにくい | 高 | App.vue に `<q-page>` を単独使用→`npm run tauri dev`→ウィンドウが白紙（見出しもボタンも出ない） | Quasar導入の落とし穴 | ✅Phase 1で修正: 最小確認はレイアウト非依存の `q-btn`＋プレーンdivに変更。HMR反映で復旧。中核S-05（Phase 2）では `q-layout`→`q-page-container`→`q-page` を正しく階層化して導入する |

### Phase 2 DA批判レビュー

**DA観点:** （開発プロセスの後始末／Quasarレイアウトの体感）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **`tauri dev` を停止しても子の vite(node) が残りポート1420を占有**→次回 `npm run tauri dev` が `Port 1420 is already in use` で失敗。**DA#4（ゾンビ子プロセス）の実例**。dev起動時の親(bash)停止だけでは子が死なない | 中 | `npm run tauri dev`→TaskStop→再度 `npm run tauri dev`→`Port 1420 already in use` で exit 1 | プロセス寿命 | ✅当面の運用: 停止後は **ポート1420のlistenプロセスを kill** してから再起動（`Get-NetTCPConnection -LocalPort 1420 | Stop-Process`）。Phase 3 の Rust側サイドカー実装で**ウィンドウ破棄時に子プロセス群を確実に kill** する設計に織り込む（DA#4と統合） |
| 2 | 右ドロワー（コンテキスト）が overlay モードで開き、**主役のタイムラインを暗転**させ可読性が落ちる | 低 | S-05起動→中央が灰色がかる | UX（主役の視認性） | ✅`q-drawer side=right` に `show-if-above` 追加でデスクトップ常時ドッキング化（背景を暗くしない）。HMR反映で改善 |

### Phase 3-A DA批判レビュー

**DA観点:** （多画面シェル化の構造的負債／使い捨てモックの陳腐化リスク）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **ドロワー開閉状態が画面ごとに独立**: 各画面が自前の `leftDrawer` ref＋`<AppNav>` を持つため、片方で閉じても遷移先で再び開く（状態が画面間で非共有） | 低 | 窓幅を狭めて S-01 のナビを閉じる→S-02 へ遷移→ナビが再表示される | 構造（状態の所在） | desktopは `show-if-above` で常時表示のため実害ほぼ無し。折りたたみ式ナビを正式採用する段で、ドロワー状態を上位（`App.vue`/簡易ストア）へ集約する |
| 2 | **q-layout/ヘッダ雛形の重複**: 8画面で `q-layout`＋ヘッダ＋`<AppNav>` の足場が重複 | 低 | 各 `S0*.vue` 冒頭の template が類似 | 重複（DRY） | 各画面でヘッダ内容が異なるため現状は許容。共通部分が増えた時点で共有レイアウト（`<AppShell>`）へ抽出 |
| 3 | **モックの固定値が陳腐化**: 「今日=7日」やダミー日付がハードコード（`S01Calendar.vue` `todayDay=7`） | 低 | 実日付に依存せず常に 6/7 が"今日" | モック前提 | 静的モックの意図的固定。3-C 以降の実データ/実時計接続で撤去（各画面冒頭コメントに「実データ接続は後フェーズ」と明記済み） |

### Phase 3-B DA批判レビュー

**DA観点:** （薄い中継層の隠れ遅延／契約の取りこぼし）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **`meta` がモデル読込＋音声decode後にしか出ない**: `meta` は「最初の合図」だが、`WhisperModel` 構築と `info.duration`（decode要）の後に emit される。base は速いが **medium 初回は数〜数十秒**「準備中」が続く | 中 | medium 指定で起動→最初の数十秒 stdout が無音 | 隠れ遅延（DA-新1の実体） | 3-C で UI は `meta` 受信まで「文字起こし準備中」スピナーに集約。さらに早い合図が要るなら `WhisperModel` 構築前に `starting` 行を足す案を将来検討 |
| 2 | **whisper スレッド数の不一致**: コード既定 `threads=8`（transcribe.py）に対し設定モック S-08 は `whisper n_threads=4`。sidecar はスレッドを引数化せず常に既定8 | 低 | sidecar 起動時のスレッドは常に8固定 | 設定連携の取りこぼし | 設定→sidecar のスレッド受け渡しは設定永続化を実装する段（別フェーズ）で統一。3-B では既定のままで可 |

### Phase 3-C DA批判レビュー

**DA観点:** （子プロセス寿命のWindows特有罠／実ウィンドウ検証の手段／疎通優先で見送った負債）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **孫プロセス(python/whisper)が残る**: `Child::kill()` は直接の子 `uv` しか終了させず、`uv run python` の **孫 python は orphan 化**してCPU/メモリを占有しうる（DA-新4の実体）。録音中に閉じると顕著 | 中 | mid-flightで閉じる→`child.kill()`だけだと python が残存 | プロセス寿命（Windows特有） | ✅**実装で解消**: `kill_sidecar` を `taskkill /T /F /PID <pid>` の**プロセスツリーkill**へ格上げ。mid-flightクローズでも uv+python が消える（exit 0・残存なし）を実測。`#[cfg(not(windows))]` は従来 `child.kill()` |
| 2 | **実ウィンドウ検証の手段が未確立**: Playwright は Tauri ランタイム非搭載で invoke/listen が動かず、ボタン操作・イベント受信を自走確認できない | 中 | S-05でボタンをPlaywrightから押せない | 検証可能性 | ✅`scripts/{shot-window,click,uia}.ps1` を新設。**AttachThreadInput で前面化→画面矩形を実ピクセルキャプチャ**（PrintWindow不要＝WebView2のGPU合成でも空白にならない）＋座標クリック。UIAはWebView2のDOMを外部へ非公開（窓枠ボタンのみ）→座標方式を採用。Rustの `eprintln!` ログが**最も確実な一次信号**（emit回数で経路を確認） |
| 3 | **既定ウィンドウ 800×600 が狭い／左ナビが折りたたみ**: 標準モニタでも `q-drawer show-if-above` の閾値に届かずナビが出ない・主役が窮屈 | 低 | 800幅起動→左ナビ非表示 | UX/検証のしやすさ | ✅`tauri.conf.json` を **1200×800・center** へ（§6の指摘を実装）。マルチモニタ混在DPIでウィンドウが復元位置へスナップ→座標ずれが起きるため、検証中は一時的に `/`→`/s05` リダイレクトで直接起動しナビ依存を排除した（検証後 `/s01` に戻済） |
| 4 | **疎通優先で見送った構造負債（Phase 2 レビュー①〜③）**: タイムラインが `q-virtual-scroll` でなく全DOM常駐／話者割当メニューが行ごと／v-forキーが index | 低〜中 | 長時間会議で数千件→CPU負担・時刻順挿入で再描画破綻 | 性能/構造（将来） | ⏭️本3-Cは「経路が通ること」優先のため**未対応で見送り**。実会議の長時間データを積む段で対応（別DD候補）。末尾追加のみの現状は実害小 |
| 5 | **`base` は warm で1秒未満完走**: 文字起こしが速すぎてUIの「逐次感」やmid-flightクローズの検証が一瞬で終わる | 低 | base起動→ほぼ即「完了」 | 検証の再現性 | 記録のみ。mid-flightクローズは250ms以内に閉じて meta 前（モデル読込中）を捕捉できた。実会議の長尺音声では逐次感は十分出る見込み（RTFはDD-010で実測済） |
