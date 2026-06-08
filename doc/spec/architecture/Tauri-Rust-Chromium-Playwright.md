# Tauri / Rust / Chromium(WebView2) / Playwright の関係とアーキテクチャ

> **目的**: 「なぜ Playwright で localhost:1420 を開いても invoke が動かないのか」「なぜ実ウィンドウには繋げるのか」を、構成要素の役割から理解するためのエンジニア向け教育ドキュメント。
> **対象読者**: 本リポジトリ（SynchroniNote / Tauri v2 + Vue/Quasar）に関わる開発者。
> **関連**: 実際の操作手段は [`CLAUDE.md`](../../../CLAUDE.md)「UI確認」節と [`scripts/tauri-cdp.mjs`](../../../scripts/tauri-cdp.mjs)。設計の正は [`基本設計書.md`](../基本設計書.md)。

---

## 0. 結論（3行）

- **Tauri アプリ = Rust製の本体プロセス＋OSのWebView**。画面は素のWeb（Vue/Quasar）で、Rustとの橋渡し（`invoke`）は **Tauri本体が自分のWebViewにだけ注入する**。
- Playwright で `localhost:1420` を**新規ブラウザ**で開くと、それは「同じWeb素材を映しただけの別物」で、橋渡しが無い＝`invoke`/Rustが動かない。
- Windows の WebView2 は中身が Chromium なので **デバッグ窓口(CDP)** を開ける。そこへ繋げば**本物のウィンドウ**を操作でき、`invoke`→Rust→実DBまで動く。

---

## 1. 登場人物（それぞれの役割）

| 要素 | 正体 | 役割 | 本リポジトリでの実体 |
|---|---|---|---|
| **Rust** | プログラミング言語／ネイティブバイナリ | アプリ本体・ビジネスロジック・DBアクセス・OS連携 | `app/src-tauri/`（`#[tauri::command]` 群、rusqlite で SQLite） |
| **Tauri** | Rust製アプリフレームワーク | 本体プロセスを作り、OSの**WebView**を埋め込み、Web↔Rust の**IPC橋**を提供 | `tauri = "2"`、`tauri.conf.json` |
| **WebView (Chromium=WebView2)** | OS提供の「ブラウザ部品」 | HTML/CSS/JS を描画する画面領域 | Windows: **WebView2**（Microsoft Edge / Chromium 製） |
| **フロントエンド** | 素のWebアプリ | 見た目・画面遷移。Rustの機能は `invoke` 経由で呼ぶ | `app/src/`（Vue 3 + Quasar + vue-router） |
| **vite** | 開発用Webサーバ／バンドラ | 開発中、フロントを `http://localhost:1420` で配信（HMR） | `npm run dev`（`beforeDevCommand`） |
| **Chromium** | オープンソースのブラウザエンジン | Chrome / Edge / WebView2 の共通の中身 | WebView2 の実体がこれ |
| **CDP** | Chrome DevTools Protocol | Chromium を**外部から操作・観測**するための通信規約(WebSocket) | `--remote-debugging-port=9222` で開く |
| **Playwright** | ブラウザ自動操作ツール | ブラウザを起動 or 既存に接続して、クリック/入力/評価/スクショ | 本リポジトリでは MCP 経由（既定は新規起動） |

### 重要な前提：Tauriの「WebView」はOS依存
Tauri は独自ブラウザを同梱しない。**OSが持つWebViewを借りる**。

| OS | WebView | エンジン | CDPで繋げる？ |
|---|---|---|---|
| **Windows** | WebView2 | **Chromium** | ✅ できる（本リポジトリの手法） |
| macOS | WKWebView | WebKit | ❌ CDP非対応（別手段が必要） |
| Linux | WebKitGTK | WebKit | ❌ CDP非対応 |

> 👉 今回の「実ウィンドウにCDP直結」は **Windows(WebView2=Chromium) だからこそ成立**する。クロスプラットフォーム前提の手順ではない点に注意（本プロジェクトは Windows 11 がターゲットなので問題なし）。

---

## 2. アーキテクチャ図

### 2-1. 実行時の構成（開発モード）

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri アプリ本体プロセス  (Rust / app.exe)                   │
│                                                               │
│   ┌───────────────────────────┐      #[tauri::command]        │
│   │  埋め込みWebView (WebView2)│◄──┐   list_meetings(...)      │
│   │  = Chromium               │   │   create_meeting(...) ...  │
│   │                           │   │        │                  │
│   │  Vue/Quasar 画面          │   │        ▼                  │
│   │   invoke('list_meetings') │   │   rusqlite → SQLite (実DB)│
│   │        │ IPC橋            │   │                           │
│   │        └────────────────► │───┘ (Tauri が注入した橋)      │
│   └───────────────────────────┘                               │
│            ▲ HTML/JS/CSS を読み込む                            │
└────────────┼──────────────────────────────────────────────────┘
             │  http://localhost:1420
        ┌────┴─────┐
        │  vite    │   開発中のみ。フロント素材を配信(HMR)
        └──────────┘     ※本番は ../dist のファイルを直接読む
```

ポイント：
- **`invoke` の橋は「本体プロセスが自分のWebViewに注入したもの」**。WebView内のJSから `window.__TAURI_INTERNALS__.invoke(...)` で呼ぶと、本体プロセスのRust関数が実行され、結果が返る。
- `localhost:1420` は**ただの素材置き場**。橋とは無関係。

### 2-2. Playwright の2モード（ここが核心）

```
【モード A：launch（新規起動）】 ← 従来Claudeがやっていた／MCP既定
   Playwright ──起動──► まっさらな Chrome
                          └─ localhost:1420 を表示
                          └─ Rust本体プロセスは無関係
                          └─ invoke の橋が無い  ❌ invoke/Rust 不可
                          （※見た目の確認はできる）

【モード B：connectOverCDP（既存に接続）】 ← 今回の手法
   Playwright/CDPクライアント ──接続──► 既に動いてる WebView2
                                         └─ = 本物のTauriウィンドウ
                                         └─ Tauriが橋を注入済み
                                         └─ ✅ invoke→Rust→実DB OK
```

同じ「Playwrightで開く」でも、**A は別物のブラウザ**、**B は本物のウィンドウ**。
最初に「できない」と判断したのは、**Aしか想定していなかった**ため。事実（Aでは動かない）は正しく、結論（操作する術が無い）が飛躍だった。

---

## 3. なぜ最初は動かず、今は動くのか（因果の整理）

| 観点 | モードA（新規Chrome） | モードB（既存WebView2にCDP接続） |
|---|---|---|
| 開いている画面 | localhost:1420 の素材 | localhost:1420 の素材（同じ） |
| プロセス | Playwrightの別Chrome | **Tauri本体のWebView2** |
| `window.__TAURI_INTERNALS__` | 無い | **有る**（本体が注入） |
| `invoke` → Rust | ❌ | ✅ |
| 実SQLite | ❌ | ✅（rusqlite経由で本物） |
| 用途 | 見た目・レイアウト確認 | ランタイム/Rust/実DB込みの操作・E2E確認 |

**たとえ**：同じ料理写真を、本物のキッチン（A無し＝モードBの本体）と「写真を貼った書き割り（モードA）」で見比べていた。書き割りはコンロが点かない（invoke不可）が、写真（見た目）は同じ。最初は書き割りだけ見て「操作不能」と判断していた。

---

## 4. CDP（Chrome DevTools Protocol）とは

- Chromium が持つ「**外部から自分を操作・観測させる**」ための WebSocket ベースの規約。
- Chrome DevTools（F12の開発者ツール）も、Playwright も Puppeteer も、内部はこのCDPで話している。
- 起動時に `--remote-debugging-port=9222` を付けると、`http://localhost:9222/json` で「開いているページ一覧」、各ページの `webSocketDebuggerUrl` に繋いでコマンド（`Runtime.evaluate` / `Input.dispatchMouseEvent` / `Page.captureScreenshot` …）を送れる。
- **WebView2 は Chromium なので同じ口を持つ**。Tauri では環境変数で渡す：

  ```bash
  # scripts/start-app.sh が自動で付与している
  export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222"
  ```

本リポジトリの [`scripts/tauri-cdp.mjs`](../../../scripts/tauri-cdp.mjs) は、Playwright本体を使わず、この CDP に直接 WebSocket で繋ぐ最小実装（依存ゼロ）。`snapshot`/`click`/`eval`/`invoke`/`shot` を提供する。

---

## 5. invokeの一往復（実例トレース）

```
WebView内JS:
  window.__TAURI_INTERNALS__.invoke('list_meetings', { year:2026, month:6 })
        │
        ▼ (Tauriが注入したIPC橋／シリアライズ)
Rust本体:  #[tauri::command] fn list_meetings(state, year, month) -> Result<Vec<Meeting>,String>
        │   rusqlite で SQLite を SELECT
        ▼
返り値 Vec<Meeting>  ──(JSONで返送)──►  JSの Promise が解決 → 13件
```
（実測：2026年6月で13件取得。画面の「SQLiteの実データを表示しています（13件）」と一致。）

---

## 6. 使い分け（実務ルール）

| やりたいこと | 使う道具 | 理由 |
|---|---|---|
| 見た目・レイアウト・CSSの確認 | Playwright MCP（`localhost:1420` 新規） | 手軽。橋は不要 |
| クリック/遷移など**ランタイムが絡む操作** | `node scripts/tauri-cdp.mjs`（実ウィンドウ） | 本物のVue/Quasarハンドラが動く |
| `invoke`→Rust→**実DB**の確認 | `node scripts/tauri-cdp.mjs invoke ...` | 本体プロセスに届く |
| ピクセル精度のドラッグ等 | `scripts/shot-window.ps1` + 座標操作 | DnD(`dragDropEnabled:false`)等は座標系が要る |

> ⚠️ `invoke` の削除/保存系は**実DBに効く**。確認用途では読み取り系（`list_*`/`get_*`）を使う。

---

## 7. Tips：Playwright「既存ブラウザ接続」の応用

今回学んだ「**Playwrightは新規起動だけでなく既存ブラウザにも繋げる**（`connectOverCDP`）」は、Tauri以外でも強力。

### 7-1. 「ログイン済みブラウザ」から自動化を始める（Google認証など）
毎回スクリプト内でログインを再現するのは面倒で壊れやすい（2要素認証・CAPTCHA・reCAPTCHA等）。代わりに：

1. **人間が1回だけ手動ログイン**しておいたブラウザを、デバッグポート付きで起動する：
   ```bash
   # 例（通常のChrome。専用プロファイルを使うのが安全）
   chrome --remote-debugging-port=9222 --user-data-dir="C:/tmp/chrome-pw"
   #  → このウィンドウで Google にログインしておく
   ```
2. **Playwrightはそのブラウザに後付けで接続**する：
   ```js
   import { chromium } from 'playwright';
   const browser = await chromium.connectOverCDP('http://localhost:9222');
   const ctx = browser.contexts()[0];          // 既存のログイン状態(Cookie/セッション)を継承
   const page = ctx.pages()[0] ?? await ctx.newPage();
   // すでにログイン済みの状態から操作を開始できる
   ```
   → セッションCookieやログイン状態をそのまま使えるので、**認証を自動化に持ち込まずに済む**。

### 7-2. 代替：認証状態を保存して使い回す（接続不要版）
常駐ブラウザを用意したくない場合は、ログイン状態をファイル化して再利用する手もある：
```js
// 一度ログインして保存
await context.storageState({ path: 'auth.json' });
// 以降はそれを読み込んで起動（毎回ログイン不要）
const context = await browser.newContext({ storageState: 'auth.json' });
```
※「既存接続(7-1)」は“生きたセッションに相乗り”、「storageState(7-2)」は“状態のスナップショットを復元”。手軽さなら後者、人間の操作と画面を共有したいなら前者。

### 7-3. 本リポジトリへの応用
同じ原理で、**起動済みTauriウィンドウ**に相乗りして、人間が開いた画面状態のまま自動操作・確認ができる（＝今回の `tauri-cdp.mjs`）。

### 7-4. セキュリティ注意（重要）
- `--remote-debugging-port` を開いたブラウザは、**ローカルから無認証で完全操作できる**口を持つ。既定で `127.0.0.1` バインドだが、**開発時のみ**に留め、ポートを外部公開しないこと。
- ログイン済みプロファイルにCDPを開くと、その認証情報も操作対象になる。**専用プロファイル（`--user-data-dir`）**を使い、業務用の常用プロファイルでは開かない。
- 本プロジェクトの方針（機密の外部送信禁止・完全ローカル）に沿い、CDPは**ローカル開発限定**で使う。

---

## 8. よくある誤解（まとめ）

| 誤解 | 実際 |
|---|---|
| 「Tauriは独自ブラウザを積んでいる」 | OSのWebViewを借りる（Win=WebView2/Chromium, mac/Linux=WebKit） |
| 「Playwright = 新しいブラウザを開くもの」 | 新規起動も既存接続(`connectOverCDP`)もできる |
| 「localhost:1420 を開けばTauriアプリ」 | それは素材だけ。`invoke`の橋は本体プロセスのWebViewにしか無い |
| 「invokeが動かない＝操作不能」 | 繋ぎ先を“本物のウィンドウ”にすれば動く |
| 「この手はどのOSでも同じ」 | CDPはChromium前提。WebView2(Windows)限定 |

---

## 参考
- 実装：[`scripts/tauri-cdp.mjs`](../../../scripts/tauri-cdp.mjs)（CDP直結ドライバ）、[`scripts/start-app.sh`](../../../scripts/start-app.sh)（デバッグポート付与）
- 運用ルール：[`CLAUDE.md`](../../../CLAUDE.md)「UI確認（Tauri/Quasar・重要）」節
- 設計の正：[`基本設計書.md`](../基本設計書.md)
