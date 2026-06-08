# scripts/ — 補助スクリプト一覧（このフォルダの入口）

SynchroniNote の開発・運用を助ける小さなスクリプト置き場。用途は **A〜C の3グループ**（引退分は `archived/` へ）。
**特記がなければリポジトリルート（`c:\repo\syncro_note`）から実行**する。
迷ったらまず下の「早見表」を見る。スクリプトを追加したらこの README にも1行足す。

## 早見表（やりたいこと → 実行）

| やりたいこと | 実行コマンド | 種別 |
|---|---|---|
| デスクトップアプリ(Tauri)を開発起動 | `bash scripts/start-app.sh` | bash |
| 〃 を停止＋ポート1420を解放 | `bash scripts/stop-app.sh` | bash |
| 〃 を配布用にビルド（インストーラ生成） | `bash scripts/build-app.sh` | bash |
| 実ウィンドウをPNGで撮る | `powershell -ExecutionPolicy Bypass -File scripts/shot-window.ps1 -Process app -Out c:/tmp/x.png` | ps1 |
| 実Tauriウィンドウを操作(invoke/Rust込み) | `node scripts/tauri-cdp.mjs snapshot` 等 | mjs |
| DD索引(DD-INDEX.md)を再生成 | `bash scripts/dd-index-gen.sh` | bash |
| doc索引(INDEX_MAP.md)のズレ検査 | `bash scripts/doc-index-check.sh [--strict]` | bash |

---

## A. デスクトップアプリ（Tauri）の起動・停止・ビルド … bash

対象: リポジトリの `app/`（Tauri+Quasar）。前提: Git Bash / Node.js(npm) / Rust(cargo)。

- **start-app.sh** — `npm run tauri dev` で開発起動。初回は Rust コンパイルで数分。起動前に残った古いポート1420(vite)を自動解放。停止は Ctrl+C か `stop-app.sh`。
- **stop-app.sh** — `tauri dev` 停止後に残りがちな vite(node) を止め、ポート1420を解放。**このリポジトリの `target` 配下の `app.exe` だけ**を終了（無関係な app.exe は巻き込まない）。
- **build-app.sh** — `npm run tauri build` で配布物を生成。成果物: `app/src-tauri/target/release/bundle/`（`nsis/*-setup.exe`, `msi/*.msi`）。
- **tauri-cdp.mjs** — 起動中の **実Tauriウィンドウ(WebView2)を Claude から操作**するドライバ。Playwright では届かない `invoke`→Rust→実SQLite まで本物を叩ける。`start-app.sh` がデバッグ窓口(CDP `localhost:9222`)を開く前提。サブコマンド: `snapshot`(画面を読む)／`text`／`click`／`eval`／`invoke <cmd> '<json>'`／`shot <png>`。詳細はファイル先頭コメントと `CLAUDE.md`「UI確認」節。

## B. 実Tauriウィンドウのスクショ … PowerShell

なぜ必要か: 素のブラウザ（Playwright）には Tauri ランタイムが無く、実ウィンドウを撮れない。**実ウィンドウの目視確認はこれで行う**。DPI 対応・物理ピクセルで座標系が一致する。`-Process` 既定は `app`。

- **shot-window.ps1** `-Process app -Out <png>` — 実ウィンドウを前面に出して PNG 保存。`CopyFromScreen` を使うため WebView2 のGPU合成画面も正しく撮れる（`PrintWindow` だと白紙になる）。

## C. ドキュメント索引の自動管理 … bash（リポジトリルートで実行）

- **dd-index-gen.sh** — `doc/DD/` から `DD-INDEX.md` を全量再生成（冪等）。手動編集禁止のインデックスはこれで更新する。`/dd rebuild-index` の実体。
- **doc-index-check.sh** `[--strict]` — `doc/`（DD除く）と `doc/INDEX_MAP.md` のズレ（未登録・リンク切れ）を検査。`--strict` はズレがあれば exit 1（フック/CI 用）。

> **live な呼び出し元に注意**: C の2本は `CLAUDE.md`・`/dd` スキル・`.claude/hooks/` から **名前で**呼ばれている。**リネーム・移動するとそれらが壊れる**ので、変更時は呼び出し元も直すこと。（※ DD（`doc/DD/`）内の言及は当時の記録なので、切れても問題ない。）

## archived/ … 引退したスクリプト（参照用・原則実行しない）

普段は使わなくなったが、参考に残すものを置く。**ここに入れたら早見表からは外す**。

- **start-ui.ps1 / stop-ui.ps1 / start-ui.bat / stop-ui.bat** — Python版UI(gradio, :7860)の起動・停止。開発の主戦場が Tauri アプリへ移ったため引退。
- **click.ps1 / uia.ps1** — 実Tauriウィンドウの座標クリック／要素操作（実験用）。通常確認は B の shot-window + Playwright で足りるため引退。
- ⚠️ **その場では動かない**: 起動系スクリプトは「`scripts/` 直下にいる」前提でパスを逆算する（→末尾の整理方針）。再び使うときは **`scripts/` 直下に戻してから**実行する。

---

## このフォルダの整理方針（将来の自分 / Claude へ）

- **現役スクリプトをサブフォルダに分けないのは意図的**。`start-app.sh` などは「`scripts/` 直下にいる」前提で、リポジトリルートや `python/` の位置を `dirname` / `Split-Path` で逆算している。階層を深くすると**内部のパス計算が狂う**（pid の gitignore も外れて誤コミットになる）。分類は物理フォルダではなく、**この README のグループ分け（A〜C）で行う**。例外は `archived/`（引退分の保管庫。原則実行しない＝パス計算は問題にならない）。
- **スクリプトを足したら**: 早見表＋該当グループ（A〜C）に1行ずつ追記する。
- **スクリプトを引退させたら**: `archived/` へ移し、早見表から外し、`archived/` 節に1行足す。
