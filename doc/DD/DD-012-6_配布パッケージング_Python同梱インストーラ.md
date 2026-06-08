# DD-012-6: 配布パッケージング（Python同梱インストーラ）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 進行中（ベース＝起動経路の抽象化を実装済み。実exeビルド/クリーン実証は移植様子見で保留） |

> 親DD: [DD-012 製品化（中核機能の実装と実用化）](DD-012_製品化_中核機能の実装と実用化.md)
> アプローチ: 標準（探索的実装。ビルド/パッケージング検証が中心。クリーン環境で確認）

## 目的

Python ランタイム＋必要モデルを同梱し、**`uv` の無いPCでもインストールするだけで動く** Windows 配布物（`.msi`/`.exe`）を生成する。DD-011 で「別DDに分離」と明記された最重要 DA（配布時のPython同梱）の本実装。あわせて**子プロセスのツリー確実 kill**（DA#4/新4 の確実版）を仕上げる。

## 背景・課題

- 開発時は `uv run` 直叩きで疎通（DD-011 Phase3）。配布物は uv 前提のままでは動かない。
- サイドカー契約（JSON Lines）を挟んでいるため、**起動を同梱exeに差し替えてもフロント/契約は無改修**で済む（DD-011 DA#1 の狙い）。
- Windows では `uv` を消しても孫（whisperワーカ）が残りうる（DD-011 DA#4/新4）。Phase3 は最小 kill のみ＝確実版は本DDで。

## 検討内容（着手時の📐で確定）

> 📐 実装前詳細化を 2026-06-08 に実施し以下で確定（配布構成＝後戻り困難のため必須）。

- **同梱方式**: PyInstaller で **単一exe**（`pipeline.dist_entry`）に集約し、第1引数 `<module>` で
  sidecar / summarize_sidecar / calendar_parse_sidecar の各 `main(argv)` へ振り分ける。個別exe×3案は
  サイズ3倍・管理煩雑のため不採用。モデル（whisper/Ollama）の同梱/取得方針は実ビルド（Phase1）で決定。
- **起動切替**: 開発=`uv run`／配布=同梱exe。**実行時検出**で自動切替（環境変数
  `SYNCHRONI_SIDECAR_EXE` → resource_dir の順で探索）。`tauri.conf.json` は今は変更せず（externalBin の
  ビルド破綻リスクを避け、後戻り可能に保つ）。フロント契約（JSON Lines）は不変（DD-011 DA#1）。
- **確実 kill**: 既存の `taskkill /T /F /PID`（PIDツリーkill）が uv/exe どちらの経路でも有効。
  追加実装は不要（DA#4/新4 は達成済み）。

## スコープ

- **やる**: Python サイドカーの同梱exe化、Tauri build への統合、起動経路の開発/配布切替、確実版 kill、**クリーン環境での動作確認**。
- **やらない**: コード署名・配布チャネル（ストア/更新）・自動アップデート（別途）。

## 依存

- 前提: 中核経路（**DD-012-1〜3**）が安定していること。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 対象パス・🔬機械検証の精査（lib.rs の uv 直叩き7経路＋kill＋各 sidecar の `main(argv)` を特定）
- [x] 📐 実装前詳細化トリガー判定（**配布構成＝後戻り困難 → 詳細化必須**）。同梱方式を比較し確定（上記「検討内容」）
- [ ] 😈 Devil's Advocate（同梱サイズ肥大・モデル配置・初回起動の遅さ・ウイルス誤検知・孫プロセス残存）※実ビルド（Phase1）で実施

### Phase 1: 同梱と起動切替
- [x] **ベース**: 起動経路を `sidecar_base()` に集約し、開発=`uv run`／配布=同梱exe を実行時検出で切替（`SIDECAR_EXE`/`resolve_sidecar_exe`）。uv 直叩き7経路を移行（lib.rs）
- [x] **ベース**: 配布exe の統一エントリ `pipeline.dist_entry`（第1引数 module で各 `main` へ委譲）を追加
- [x] 子プロセスのツリー確実 kill（既存 `taskkill /T /F /PID` が uv/exe 両経路で有効＝達成済み）
- [x] ベース検証: `cargo check` 警告なし／`uv run … dist_entry sidecar --list-devices` で devices JSON 取得／exe未配置時は uv フォールバックで現状維持
- [ ] PyInstaller `.spec` 作成→単一exe化（hidden-imports/データ同梱の実地調整）※移植様子見で保留
- [ ] `tauri.conf.json` `bundle.resources` へ exe 同梱・配置名（`synchroni-sidecar.exe`）確定 ※保留
- [ ] 🔬 機械検証: `scripts/build-app.sh` 成果物が生成され `.msi`/`.exe` が作られる ※保留
- [ ] 😈 DA批判レビュー（最低1件）※実ビルド時

### Phase 2: クリーン環境での実証 ※保留（DD-014 Rust移植の様子見後に実施）
- [ ] 🔬 機械検証（**実環境**）: uv/Python 未インストールのクリーン環境（別ユーザー/VM）にインストール→起動→サンプル音声で文字起こし→終了でプロセス残存なし。証跡を `DD-012-6/` に保存
- [ ] 😈 DA批判レビュー（最低1件）

## 完了条件（DoD）

- uv/Python の無いクリーン環境で、インストール→起動→文字起こしが動く。
- ウィンドウ終了で裏方プロセス（孫含む）が残らない。

## ログ

### 2026-06-08
- DD作成（親 DD-012 の子）。DD-011 DA#1（配布時Python同梱）の本実装＋DA#4確実版killの仕上げとして起票。中核（012-1〜3）安定後に着手。

### 2026-06-08（ベース実装）
- **着手判断**: 中核(012-1〜3)は安定済みで着手可。ただし P4-3 Rust移植(DD-014)が進行中で配布の「中身」が変わりうるため、後戻りに強い**起動経路の抽象化（骨組み）だけ先行**。実exeビルド/クリーン実証は移植様子見で保留（ユーザー合意）。
- **実装**: `app/src-tauri/src/lib.rs` に `sidecar_base()` / `resolve_sidecar_exe()` / `static SIDECAR_EXE` を追加し、uv 直叩きだった7経路（STT本流 `spawn_and_relay`＋抽出/カレンダー/デバイス列挙の3ブロッキング）を集約。`python/src/synchroni_note/pipeline/dist_entry.py`（配布exe の統一エントリ）を追加。
- **検証**: `cargo check` 警告なし。`uv run … dist_entry sidecar --list-devices` で `type=devices` JSON 取得＝ディスパッチ正常。exe 未配置時は `SIDECAR_EXE=None`→uv 経路で**現状維持**（引数列は旧実装と一致を机上確認）。
- **次（保留）**: PyInstaller spec→単一exe化、`tauri.conf.json` の `bundle.resources` 同梱と配置名確定、クリーン環境実証、モデル（whisper/Ollama）同梱・取得方針の決定。

---

## DA批判レビュー記録

### Phase N DA批判レビュー

**DA観点:** （このPhaseで最も壊れやすいポイントは何か？）

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | | | | | |
