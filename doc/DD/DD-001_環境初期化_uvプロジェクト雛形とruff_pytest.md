# DD-001: 環境初期化（uvプロジェクト雛形＋ruff/pytest）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 完了 |

> アプローチ: 標準（探索的実装）。環境構築タスクで、画面・ビジネスロジック・バグ修正のいずれにも該当しないため。
> ロードマップ対応: [開発ロードマップ.md](../plan/開発ロードマップ.md) の **Phase 0 / P0-1**。

## 目的

SynchroniNote の評価・MVP実装の土台となる Python プロジェクトを uv で初期化し、ruff（Lint/Format）と pytest を動く状態にする。以降の P0-2（LLM速度ベンチ）・P0-3（STT速度ベンチ）・Phase1 MVP がこの雛形の上に乗る。

## 背景・課題

- ロードマップの基本方針で「評価フェーズはPython優先（uv/ruff）」と決定済み。まず開発基盤を整える必要がある。
- uv / ruff / Python 3.13.8 は導入済みだが、プロジェクト構成（pyproject.toml・srcレイアウト・lint/test設定）が未整備。
- 製品期に Rust(Tauri) を別途追加するため、Python評価コードとの配置を最初に決めておく。

## 検討内容

**配置レイアウト（Tauri導入を見据えたモノレポ）**
- 案A: リポジトリ直下に `pyproject.toml` + `src/synchroni_note/`。
  - → ❌不採用。Tauri は慣例上ルートに `src/`（フロントエンド）と `src-tauri/`（Rust）を置くため、Pythonの `src/` と衝突する。
- 案B: Python を `python/` 配下に、将来のTauriを `app/` 配下にまとめる。
  - → **案B採用**。各スタックをディレクトリで明確に分離し、衝突を避ける。

```
syncro_note/
├── doc/
├── python/            # 本DDで作成（uvプロジェクト）
│   ├── pyproject.toml
│   ├── .python-version
│   ├── src/synchroni_note/
│   └── tests/
├── app/               # 将来フェーズ（Tauri）
│   ├── src/           #   フロントエンド (TS/React/Yjs)
│   └── src-tauri/     #   Rust (cpal/whisper-rs)
└── .gitignore         # ルート共通
```

**ruff 設定**
- line-length=100、target-version=py313、lint は E/F/I（pyflakes・pycodestyle・isort相当）を基本に開始。formatも ruff に統一（black不要）。

**テスト**
- pytest を採用。`tests/` 配下。最初はスモークテスト1本（パッケージがimportできること）のみ。

**依存管理**
- ランタイム依存はこのDDでは入れない（STT/LLMクライアントは P0-2/P0-3 で追加）。dev依存に ruff・pytest を `uv add --dev` で登録。

## 決定事項

- **`python/` 配下**に uv プロジェクトを作成（srcレイアウト: `python/src/synchroni_note/`、`python/tests/`）。将来のTauriは `app/` 配下に分離し衝突を回避。
- Python 3.13 固定（`.python-version` / `requires-python = ">=3.13"`）。
- ruff で Lint + Format を一元化。pytest でテスト。
- dev依存のみ追加（ruff, pytest）。ランタイム依存は後続DDで追加。
- `.gitignore` は**リポジトリ直下**に置き、Python成果物（`.venv/`・`__pycache__/`・`.pytest_cache/`・`.ruff_cache/` 等）を無視。将来Tauri分（`node_modules/`・`target/` 等）は該当フェーズで追記。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 **各Phaseのタスク精査・詳細化**（対象パス・具体的変更・🔬機械検証が揃っているか）
- [x] 📐 **実装前詳細化トリガー判定**
  - 規模シグナル: 新規モジュール追加に該当するが、内容は標準的な雛形生成のみ。
  - 複雑度シグナル: 該当なし（ロジック・並行処理・スキーマ・セキュリティ境界なし）。
  - 判定結果: **Phase 1 → 詳細化不要**（設計判断を伴わない定型スキャフォールドのため）。
- [x] 😈 **Devil's Advocate調査**
  - 将来Tauri追加時にディレクトリが衝突しないか？ → Python=`python/`、Tauri=`app/` に分離して回避（案B）。
  - ruff のルール過多で初期に警告が出すぎないか？ → 最小セット(E/F/I)から開始し段階的に拡張。
  - Python 3.13 固定で将来のライブラリ（faster-whisper等）が対応するか？ → P0-2/P0-3 着手時に動作確認、問題あればバージョン見直し。

### Phase 1: プロジェクト雛形の作成（`python/` 配下）
- [x] `python/pyproject.toml` を作成（`[project]` name=synchroni-note, requires-python=">=3.13", `[dependency-groups] dev=[ruff, pytest]`, `[tool.ruff]` line-length=100/target=py313/lint select=["E","F","I"], `[tool.pytest.ini_options]` testpaths=["tests"]。hatchlingビルド設定とpythonpath=["src"]も追加）
- [x] `python/.python-version` に `3.13` を記載
- [x] `python/src/synchroni_note/__init__.py` を作成（`__version__` 定義）
- [x] `python/tests/test_smoke.py` を作成（`import synchroni_note` が成功し `__version__` が文字列であること）
- [x] リポジトリ直下 `.gitignore` に Python/uv セクションを追加
- [x] `python/` で `uv sync` を実行し仮想環境と依存を解決（ruff 0.15.16 / pytest 9.0.3 が入った）
- [x] 🔬 **機械検証**（`python/` 配下で実行・全て緑）:
  - `uv run ruff check .` → `All checks passed!`
  - `uv run ruff format --check .` → `2 files already formatted`
  - `uv run pytest -q` → `1 passed`
- [x] 😈 **DA批判レビュー（下記記録）**

## ログ

### 2026-06-07
- DD作成
- ユーザー指示によりTauri想定のモノレポ構成（Python=`python/` / Tauri=`app/`）へ方針変更
- `python/` 配下に雛形作成、機械検証3点すべて緑で完了

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー

**DA観点:** 雛形構成・設定が後続フェーズ（P0-2/P0-3 ベンチ、Phase1 MVP）の障害にならないか。

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | `.gitignore` が `*.wav/*.mp3` 等を無視するため、P0-3のCER測定に使う評価用サンプル音声がgit管理外になる。保管・参照方法（ローカル固定パス or 別ストレージ）を決める必要 | 中 | P0-3着手時に `python/` へ音声を置いてもコミットされず、別PC/再現で欠落 | 将来フェーズの前提崩れ | ⏭️別DD（P0-3で音声配置方針を決定） |
| 2 | dev依存を `ruff>=0.8`/`pytest>=8` と緩めに指定したため実際は ruff 0.15 / pytest 9 が入った。ルール挙動が将来のバージョンで変わりうる | 低 | `uv sync` 時に最新が入る | 再現性 | ❌不要（uv.lockで固定済。問題が出たら厳密ピン） |
