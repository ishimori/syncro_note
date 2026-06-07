# DD-011: Phase4 Tauri 2ペインUI骨格 — Python中身に接続

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 進行中 |

> アプローチ: 標準（探索的実装）。画面の「見た目の合意」は DD-009（[doc/spec/画面設計書.md](../spec/画面設計書.md)）＋ HTMLモック（[doc/mock/html/](../mock/html/)）で確定済みのため、本DDは**雛形作成＋中身（Python）との疎通**という振る舞い中心の作業。

## 進捗サマリ（2026-06-07 時点・一旦区切り）

| Phase | 状態 | 成果物 |
|-------|------|--------|
| Phase 0 事前精査 | ✅完了 | 詳細化判定（P1/P3=要）・DA 5件（最重要=配布時Python同梱→別DD） |
| Phase 1 Tauri+Quasar雛形 | ✅完了 | `app/`（Tauri2+Vue+TS+Quasar）。ウィンドウ起動・ボタン操作までユーザー目視OK |
| Phase 2 S-05画面骨格（静的） | ✅完了 | `app/src/pages/S05Realtime.vue`（モック忠実）。Playwrightで自走目視確認。証跡 [DD-011/s05-phase2-after.png](DD-011/s05-phase2-after.png) |
| **Phase 3 Python中身に接続** | ⏳**未着手（次回ここから）** | 着手前に 📐詳細設計→👀レビュー が必要（外部I/F=サイドカー契約のため） |

**次回の入口**: Phase 3 の📐実装前詳細化（サイドカーのJSON Lines契約・Python実行口・Rust spawn＋イベント中継）を作り、👀レビュー後にコーディング。下記 Phase 0 DA #1〜4（配布時同梱は別DD／UTF-8／unbuffered／子プロセスkill）を設計に織り込む。Phase 3 はTauriランタイム依存のためPlaywright不可＝実ウィンドウ併用で確認。

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

### Phase 3: Python中身に接続（📐詳細化要 → 👀レビュー後に着手）

> **設計入力（コードレビュー由来・厳選）**: Phase 2 のレビューで多数の指摘が出たが、骨格＝Phase 3で作り直す前提で**今のコード変更はしない**と判断。本物の設計事項3点のみ Phase 3 詳細設計に織り込む: ①**タイムラインは `q-virtual-scroll`**（長時間会議で数千件→全DOM常駐はCPU負担。本機はCPUのみでSTT/LLMとCPUを食い合う）②**話者割当メニューは行ごとでなく共有1個**③**v-forのkeyはバックエンド採番の安定IDを使う**（末尾追加だけなら現状の index key でも実害ないが、時刻順挿入/後追い整形が入ると壊れるため実データID前提に）。その他の指摘（deep reactive→shallow化, displayName毎回呼び, CSS/アイコン全読み, デモ時刻のslice 等）は時期尚早/難癖/使い捨てデモのため**対応不要**と判断。

- [ ] 📐 **実装前詳細化**: サイドカー契約（JSON Lines のスキーマ＝`{type, text, seq, ...}`）・Python実行口の置き場（`python/src/synchroni_note/` 配下に薄いサブコマンド）・Rust側 spawn と Tauri イベント名 → 👀ユーザーレビュー
- [ ] Python 側: 既存 `stream_transcribe` を **JSON Lines で標準出力に流す薄い実行口**を追加（サンプル音声パスを引数に）
- [ ] Rust(Tauri) 側: 上記を**サイドカーとして spawn**し、stdout を1行ずつ読んでフロントへ Tauri イベントで中継
- [ ] フロント: 受信イベントを**左ペインへ逐次追記**表示
- [ ] 🔬 **機械検証**: サンプル音声（[python/audio/](../../python/audio/)）を指定→**左ペインに文字起こしが逐次表示**される（録画 or 連続スクショ）
- [ ] 😈 **DA批判レビュー（最低1件）**

## ログ

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
