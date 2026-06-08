# DD-012-6: 配布パッケージング（Python同梱インストーラ）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-09 | 進行中（Phase1ほぼ完了: PyInstaller単一exe(onedir)化を実装・実機STT実証済み／最小構成を採用。残=Tauri同梱→.msi生成と実機クリーン検証） |

> 親DD: [DD-012 製品化（中核機能の実装と実用化）](archived/DD-012_製品化_中核機能の実装と実用化.md)（**完了・アーカイブ済み**。本DDは配布の独立継続タスク）
> アプローチ: 標準（探索的実装。ビルド/パッケージング検証が中心。クリーン環境で確認）

## 目的

Python ランタイム＋必要モデルを同梱し、**`uv` の無いPCでもインストールするだけで動く** Windows 配布物（`.msi`/`.exe`）を生成する。DD-011 で「別DDに分離」と明記された最重要 DA（配布時のPython同梱）の本実装。あわせて**子プロセスのツリー確実 kill**（DA#4/新4 の確実版）を仕上げる。

> 配布構成は 2026-06-09 に**最小構成**へ確定（モデルは非同梱・受領者が用意）。下記「配布構成の決定」を参照。

## 背景・課題

- 開発時は `uv run` 直叩きで疎通（DD-011 Phase3）。配布物は uv 前提のままでは動かない。
- サイドカー契約（JSON Lines）を挟んでいるため、**起動を同梱exeに差し替えてもフロント/契約は無改修**で済む（DD-011 DA#1 の狙い）。
- Windows では `uv` を消しても孫（whisperワーカ）が残りうる（DD-011 DA#4/新4）。Phase3 は最小 kill のみ＝確実版は本DDで。

## 検討内容（着手時の📐で確定）

> 📐 実装前詳細化を 2026-06-08 に実施し以下で確定（配布構成＝後戻り困難のため必須）。

- **同梱方式**: PyInstaller で **単一exe**（`pipeline.dist_entry`）に集約し、第1引数 `<module>` で
  sidecar / summarize_sidecar / calendar_parse_sidecar の各 `main(argv)` へ振り分ける。個別exe×3案は
  サイズ3倍・管理煩雑のため不採用。実ビルドでは **onefile ではなく onedir** を採用（毎回自己展開の初回遅延・AV誤検知を避け、Rust の `sidecar/synchroni-sidecar.exe` 探索と整合）。
- **起動切替**: 開発=`uv run`／配布=同梱exe。**実行時検出**で自動切替（環境変数
  `SYNCHRONI_SIDECAR_EXE` → resource_dir の順で探索）。`tauri.conf.json` は今は変更せず（externalBin の
  ビルド破綻リスクを避け、後戻り可能に保つ）。フロント契約（JSON Lines）は不変（DD-011 DA#1）。
- **確実 kill**: 既存の `taskkill /T /F /PID`（PIDツリーkill）が uv/exe どちらの経路でも有効。
  追加実装は不要（DA#4/新4 は達成済み）。

## スコープ

- **やる**: Python サイドカーの同梱exe化、Tauri build への統合、起動経路の開発/配布切替、確実版 kill、**クリーン環境での動作確認**。
- **やらない**: コード署名・配布チャネル（ストア/更新）・自動アップデート（別途）。**最小構成のため AIモデル/Ollama 自体の同梱はしない**（受領者が用意）。

## 依存

- 前提: 中核経路（**DD-012-1〜3**）が安定していること。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 対象パス・🔬機械検証の精査（lib.rs の uv 直叩き7経路＋kill＋各 sidecar の `main(argv)` を特定）
- [x] 📐 実装前詳細化トリガー判定（**配布構成＝後戻り困難 → 詳細化必須**）。同梱方式を比較し確定（上記「検討内容」）
- [x] 😈 Devil's Advocate（同梱サイズ肥大・モデル配置・初回起動の遅さ・ウイルス誤検知・孫プロセス残存）→ 実ビルドで実施（下記 DA 記録）

### Phase 1: 同梱と起動切替
- [x] **ベース**: 起動経路を `sidecar_base()` に集約し、開発=`uv run`／配布=同梱exe を実行時検出で切替（`SIDECAR_EXE`/`resolve_sidecar_exe`）。uv 直叩き7経路を移行（lib.rs）
- [x] **ベース**: 配布exe の統一エントリ `pipeline.dist_entry`（第1引数 module で各 `main` へ委譲）を追加
- [x] 子プロセスのツリー確実 kill（既存 `taskkill /T /F /PID` が uv/exe 両経路で有効＝達成済み）
- [x] ベース検証: `cargo check` 警告なし／`uv run … dist_entry sidecar --list-devices` で devices JSON 取得／exe未配置時は uv フォールバックで現状維持
- [x] PyInstaller `.spec` 作成→単一exe化（**onedir**）。faster-whisper の VAD アセット(.onnx)を `collect_data_files` で同梱、不要重量級(pandas/PIL等)を除外。`python/synchroni-sidecar.spec`（2026-06-09）
- [x] 🔬 機械検証（実機・束ねたexe単体／Python・uv 非使用）: `sidecar --list-devices` で実デバイスJSON ＋ `sidecar <wav> --model tiny` で**実STT文字起こし成功**（2026-06-09）
- [ ] `tauri.conf.json` `bundle.resources` へ exe 同梱・配置名（`sidecar/synchroni-sidecar.exe`）確定 ※下記「配布構成の決定」のマッピングを実ビルドで確定
- [ ] 🔬 機械検証: `scripts/build-app.sh` 成果物が生成され `.msi`/`.exe` が作られる ※並行UI作業(DD-016)が型エラー含み得るため、フロント安定時に実施
- [x] 😈 DA批判レビュー（onedir採用／UPXオフ／VADアセット欠落の検出と修正／サイズ削減＝下記 DA 記録）

### Phase 2: クリーン環境での実証 ※DD-014見送り（2026-06-09アーカイブ）で解禁。Python・uv 無しの実機/VM が必要
- [ ] 🔬 機械検証（**実環境**）: uv/Python 未インストールのクリーン環境（別ユーザー/VM）にインストール→起動→サンプル音声で文字起こし→終了でプロセス残存なし。証跡を `DD-012-6/` に保存
- [ ] 😈 DA批判レビュー（最低1件）

## 完了条件（DoD）

- uv/Python の無いクリーン環境で、インストール→起動→文字起こしが動く。
- ウィンドウ終了で裏方プロセス（孫含む）が残らない。

## 配布構成の決定（2026-06-09・最小構成を採用）

> ユーザー判断: モデル類は同梱せず「**最小構成**」で配布する（インストーラ最小・受領者が前提を用意）。
> DD-014（ホットパス Rust 移植）が 2026-06-09 に見送り・アーカイブされ「中身は Python のまま確定」したため、本DDの保留が解除された。

**インストーラに入れるもの**: アプリ本体 ＋ sidecar 単体プログラム（PyInstaller onedir。Python/uv 不要）。

**受領者が用意するもの（セットアップ手順）**:
1. **Ollama**: 公式インストーラで導入し、モデルを取得（`ollama pull qwen3:8b`〔ライブ整形〕／清書用バッチモデル〔gemma系〕）。アプリは `localhost:11434` の Ollama に接続する。要約・予定取込に必須。
2. **文字起こしモデル（faster-whisper）**: 既定 `medium`。初回起動時にネット接続があれば HuggingFace から自動取得され HF キャッシュに保存（以降オフライン）。完全オフライン専用機に配る場合は HF キャッシュごと持ち込む。
3. **話者IDモデル（任意）**: `campplus_sv_zh-cn_16k-common.onnx` を実行ファイル隣の `models/` に置くと高精度話者分離。無くても numpy 簡易方式に自動フォールバック（2026-06-09 実証済み）。

**Tauri 同梱（実ビルドで適用・確定）**:
- `app/src-tauri/tauri.conf.json` の `bundle.resources` に sidecar の onedir を追加し、Rust の `resolve_sidecar_exe`（`resource_dir()/sidecar/synchroni-sidecar.exe`）と一致させる。マッピング案:
  `"resources": { "../../python/dist/synchroni-sidecar": "sidecar" }`
  → 実ビルド後に成果物が `…/resources/sidecar/synchroni-sidecar.exe` になるかを確認し、ネストずれがあればマッピングか Rust 側パスを合わせる（フロント契約は不変）。
- ビルド前でも `SYNCHRONI_SIDECAR_EXE=<built exe>` を与えれば（`bash scripts/start-app.sh` 等）、.msi 化前に「exe 経路で実アプリが動くか」を実機検証できる（`resolve_sidecar_exe` の env 優先分岐）。

## ログ

### 2026-06-08
- DD作成（親 DD-012 の子）。DD-011 DA#1（配布時Python同梱）の本実装＋DA#4確実版killの仕上げとして起票。中核（012-1〜3）安定後に着手。

### 2026-06-08（ベース実装）
- **着手判断**: 中核(012-1〜3)は安定済みで着手可。ただし P4-3 Rust移植(DD-014)が進行中で配布の「中身」が変わりうるため、後戻りに強い**起動経路の抽象化（骨組み）だけ先行**。実exeビルド/クリーン実証は移植様子見で保留（ユーザー合意）。
- **実装**: `app/src-tauri/src/lib.rs` に `sidecar_base()` / `resolve_sidecar_exe()` / `static SIDECAR_EXE` を追加し、uv 直叩きだった7経路（STT本流 `spawn_and_relay`＋抽出/カレンダー/デバイス列挙の3ブロッキング）を集約。`python/src/synchroni_note/pipeline/dist_entry.py`（配布exe の統一エントリ）を追加。
- **検証**: `cargo check` 警告なし。`uv run … dist_entry sidecar --list-devices` で `type=devices` JSON 取得＝ディスパッチ正常。exe 未配置時は `SIDECAR_EXE=None`→uv 経路で**現状維持**（引数列は旧実装と一致を机上確認）。
- **次（保留）**: PyInstaller spec→単一exe化、`tauri.conf.json` の `bundle.resources` 同梱と配置名確定、クリーン環境実証、モデル（whisper/Ollama）同梱・取得方針の決定。

### 2026-06-09
- **DD-014 見送り（同日アーカイブ）で本DD解禁** → 中身は Python のまま確定し、配布は「最小構成」をユーザーが選択（モデル非同梱）。「次（保留）」だった項目に着手。
- **PyInstaller 単一 exe 化（Phase1 の核）を実装・実機実証**:
  - `python/synchroni-sidecar.spec` を追加（onedir）。`dist_entry` を単一エントリに、`pathex=src`。**onedir 採用**（onefile の毎回自己展開＝初回遅延・AV誤検知を回避）、**UPX オフ**（AV誤検知対策）、不要重量級（pandas/PIL/pydub/matplotlib 等）を `excludes`、faster-whisper の **Silero VAD アセット(.onnx) を `collect_data_files` で同梱**。
  - 依存追加: `pyinstaller`（dev）。ビルド: `uv run --project python pyinstaller --noconfirm --distpath python/dist --workpath python/build python/synchroni-sidecar.spec`。成果物 `python/dist/synchroni-sidecar/`（**279MB**, gitignore 済み）。
  - 🔬 実機実証（束ねた exe 単体・Python/uv 非使用）: ① `sidecar --list-devices` で実デバイス JSON（sounddevice/PortAudio 同梱OK）／② `sidecar python/audio/sample01.wav --model tiny` で**実 STT 文字起こし成功**（meta＋日本語 segment 群・話者ラベル）。faster-whisper＋ctranslate2＋av＋VAD が同梱 exe で動作。話者IDの ONNX は未配置のため簡易クラスタにフォールバック（想定どおり）。
  - 切り分け: 本番 STT は **faster-whisper**（pywhispercpp はベンチ専用＝非同梱）。`--list-devices` だけでは出ず STT を流して初めて出た「VAD アセット欠落」を実証検出→修正済み。
- **残**: ① `tauri.conf.json` の `bundle.resources` 適用＋ `.msi`/`.exe` 実ビルド（並行 DD-016 の UI 編集中はフロント型エラーで巻き込まれ得るため、安定状態のときに実施）② 実機クリーン環境（Python/uv 無し）での install→起動→文字起こし→終了プロセス0 の最終検証（VM/別PC 要）。

---

## DA批判レビュー記録

### Phase 1 DA批判レビュー（実ビルド時・2026-06-09）

**DA観点:** （束ねた exe で実行時に壊れる点・配布品質＝サイズ/起動/AV誤検知）

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | faster-whisper 同梱の VAD アセット `silero_vad_v6.onnx` が PyInstaller に拾われず STT が `File doesn't exist` で落ちる | 高 | `--list-devices` では露見せず、`sidecar <wav>` の STT 実行時に発生 | データ同梱漏れ | ✅ `.spec` で `collect_data_files("faster_whisper")` を datas に追加。再ビルドで `_internal/faster_whisper/assets/silero_vad_v6.onnx` の同梱と STT 成功を確認 |
| 2 | onefile は起動毎に自己展開し初回遅延＋AV誤検知を招く（頻繁起動の sidecar に不適） | 中 | onefile 配布で都度展開・誤検知 | 配布品質/RT | ✅ onedir 採用＋UPXオフ。Rust の `sidecar/synchroni-sidecar.exe` 探索と整合 |
| 3 | 不要重量級（pandas/PIL/pydub/matplotlib）混入でサイズ肥大 | 低 | 既定ビルドで 314MB | サイズ | ✅ `excludes` で 279MB に削減（STT/要約/抽出/収音/話者分離はいずれも不要を確認） |
