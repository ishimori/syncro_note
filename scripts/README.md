# scripts/ — 補助スクリプト一覧（このフォルダの入口）

SynchroniNote の開発・運用を助ける小さなスクリプト置き場。用途は **A〜D の4グループ**。
**特記がなければリポジトリルート（`c:\repo\syncro_note`）から実行**する。
迷ったらまず下の「早見表」を見る。スクリプトを追加したらこの README にも1行足す。

## 早見表（やりたいこと → 実行）

| やりたいこと | 実行コマンド | 種別 |
|---|---|---|
| デスクトップアプリ(Tauri)を開発起動 | `bash scripts/start-app.sh` | bash |
| 〃 を停止＋ポート1420を解放 | `bash scripts/stop-app.sh` | bash |
| 〃 を配布用にビルド（インストーラ生成） | `bash scripts/build-app.sh` | bash |
| Python版UI(gradio)を起動（→ :7860） | `scripts\start-ui.bat`（ダブルクリック可） | ps1/bat |
| 〃 を停止 | `scripts\stop-ui.bat` | ps1/bat |
| 実ウィンドウをPNGで撮る | `powershell -ExecutionPolicy Bypass -File scripts/shot-window.ps1 -Process app -Out c:/tmp/x.png` | ps1 |
| 実ウィンドウの座標をクリック | `powershell -ExecutionPolicy Bypass -File scripts/click.ps1 -X 100 -Y 200` | ps1 |
| 実ウィンドウの要素を名前で操作 | `powershell ... -File scripts/uia.ps1 -List`（一覧）/ `-Invoke "ボタン名"` | ps1 |
| DD索引(DD-INDEX.md)を再生成 | `bash scripts/dd-index-gen.sh` | bash |
| doc索引(INDEX_MAP.md)のズレ検査 | `bash scripts/doc-index-check.sh [--strict]` | bash |

---

## A. デスクトップアプリ（Tauri）の起動・停止・ビルド … bash

対象: リポジトリの `app/`（Tauri+Quasar）。前提: Git Bash / Node.js(npm) / Rust(cargo)。

- **start-app.sh** — `npm run tauri dev` で開発起動。初回は Rust コンパイルで数分。起動前に残った古いポート1420(vite)を自動解放。停止は Ctrl+C か `stop-app.sh`。
- **stop-app.sh** — `tauri dev` 停止後に残りがちな vite(node) を止め、ポート1420を解放。**このリポジトリの `target` 配下の `app.exe` だけ**を終了（無関係な app.exe は巻き込まない）。
- **build-app.sh** — `npm run tauri build` で配布物を生成。成果物: `app/src-tauri/target/release/bundle/`（`nsis/*-setup.exe`, `msi/*.msi`）。

## B. Python版UI（gradio）の起動・停止 … PowerShell / bat

対象: リポジトリの `python/`（`uv run synchroni-note-ui`）。URL: http://127.0.0.1:7860。

- **start-ui.ps1** / **start-ui.bat** — gradio UI を起動（`.bat` はダブルクリック用ランチャ）。多重起動防止つき（ポート使用中ならスキップ）。
- **stop-ui.ps1** / **stop-ui.bat** — ポート7860 のサーバと記録 PID を停止。
- **.synchroni-ui.pid** — start-ui が書き／stop-ui が読む **実行中PIDの自動生成ファイル**。手で触らない（gitignore 済み）。

## C. 実Tauriウィンドウの操作（スクショ / クリック / 要素操作）… PowerShell

なぜ必要か: 素のブラウザ（Playwright）には Tauri ランタイムが無く、実ウィンドウを動かせない。**実ウィンドウの目視確認・自動操作はこの3本で行う**。すべて DPI 対応・物理ピクセルで座標系が一致する。`-Process` 既定は `app`。

- **shot-window.ps1** `-Process app -Out <png>` — 実ウィンドウを前面に出して PNG 保存。`CopyFromScreen` を使うため WebView2 のGPU合成画面も正しく撮れる（`PrintWindow` だと白紙になる）。
- **click.ps1** `-X <px> -Y <px>` — ウィンドウ相対座標でクリック。座標は shot-window のキャプチャ基準。
- **uia.ps1** `-List` / `-Invoke "名前"` — UI Automation で WebView2 のDOM要素を名前で探し、一覧表示またはクリック。`-Maximize` で最大化してから実行も可。

## D. ドキュメント索引の自動管理 … bash（リポジトリルートで実行）

- **dd-index-gen.sh** — `doc/DD/` から `DD-INDEX.md` を全量再生成（冪等）。手動編集禁止のインデックスはこれで更新する。`/dd rebuild-index` の実体。
- **doc-index-check.sh** `[--strict]` — `doc/`（DD除く）と `doc/INDEX_MAP.md` のズレ（未登録・リンク切れ）を検査。`--strict` はズレがあれば exit 1（フック/CI 用）。

> **live な呼び出し元に注意**: D の2本は `CLAUDE.md`・`/dd` スキル・`.claude/hooks/` から **名前で**呼ばれている。**リネーム・移動するとそれらが壊れる**ので、変更時は呼び出し元も直すこと。（※ DD（`doc/DD/`）内の言及は当時の記録なので、切れても問題ない。）

---

## このフォルダの整理方針（将来の自分 / Claude へ）

- **サブフォルダに分けていないのは意図的**。`start-app.sh`・`start-ui.ps1` などは「`scripts/` 直下にいる」前提で、リポジトリルートや `python/` の位置を `dirname` / `Split-Path` で逆算している。階層を深くすると**内部のパス計算が狂う**（pid の gitignore も外れて誤コミットになる）。分類は物理フォルダではなく、**この README のグループ分け（A〜D）で行う**。
- **スクリプトを足したら**: 早見表＋該当グループ（A〜D）に1行ずつ追記する。
