# SynchroniNote プロジェクト設定

リアルタイムAI協調型ローカル議事録システム『SynchroniNote（シンクロニ・ノート）』。
このファイルは DD-Know-How をベースにした Claude Code 設定です。

## 主要ドキュメント

- **ドキュメント索引マップ（doc/配下の地図・入口）**: `doc/INDEX_MAP.md`
- **プロジェクト概要**: `README.md`
- **企画書（最終形の設計）**: `doc/plan/企画書.md`
- **開発ロードマップ（実行計画・フェーズ・評価指標）**: `doc/plan/開発ロードマップ.md`
- **機能仕様書（最終形・全5ファイル）**: `doc/plan/要件/0_index.md`
- **基本設計書（設計SSOT・実装の正）**: `doc/spec/基本設計書.md` ← アーキ/データ構造/モデル選定/話者分離/モデル切替は本書が正。要件と食い違えば本書を優先

> `doc/` 配下のどこに何があるかは **`doc/INDEX_MAP.md`** を起点に辿る。`doc/DD/` は対象外（下記「DD設定」で別管理）。

## ドキュメント索引（INDEX_MAP）の維持

`doc/INDEX_MAP.md` は `doc/` 配下のドキュメント全体の地図（手動キュレーション）。**`doc/DD/` 配下は対象外**（アーカイブ `doc/DD/archived/` を含む。DDは `DD-INDEX.md` で別管理）。

**メンテナンス規約（必須）**:

- `doc/` 配下（`doc/DD/` を除く）の文書を **追加・移動・改名・削除** したら、**同じ作業の中で `doc/INDEX_MAP.md` を更新する**（該当行の追加／パス修正／削除）。追加・移動時は「いつ読むか」の1行説明を必ず付ける。
- DD（`doc/DD/` 配下、アーカイブ `doc/DD/archived/` を含む）は INDEX_MAP に載せない。DDは `bash scripts/dd-index-gen.sh`／`/dd` スキルで管理する。
- **完了前ゲート（必須）**: 上記の変更を行った作業では、報告前に必ず `bash scripts/doc-index-check.sh --strict` を実行し、**exit 0（同期OK）を確認する**。未登録・リンク切れが出たら INDEX_MAP を直してから完了とする。

**自動フック化（任意・要手動登録）**:

- 現状は上記の規約＋手動実行で運用する（フックによる強制ではない）。
- フックで自動化する場合は `Stop` もしくは `PostToolUse(Edit|Write)` で `bash scripts/doc-index-check.sh` を起動する。ただし **`.claude/settings.json` は `pre-edit-guard.sh` により編集ブロックされるため、フック登録はユーザーが手動で行う**必要がある（Claude からは変更不可）。

## DD設定

- **DDフォルダ**: `doc/DD/`
- **アーカイブ**: `doc/DD/archived/`
- **テンプレート**: `doc/templates/dd_template.md`
- **インデックス**: `doc/DD/DD-INDEX.md`

## 利用可能なスキル

> スキルは `.claude/skills/` に配置されています（skills形式）

### DD管理
- `/dd new タイトル` - 新規DD作成
- `/dd list` - DD一覧
- `/dd log メモ` - ログ追記
- `/dd archive 番号` - アーカイブ
- `/dd search キーワード` - DD検索
- `/dd rebuild-index` - インデックス再構築
- DA メソッド: `doc/da-method.md`（DA品質フィルター・再チェック条件）

## 開発フロー

詳細は `doc/development-flow.md`（5ステップ）を参照。
各タスクは `doc/plan/開発ロードマップ.md` の「DD候補」を起点に `/dd new` でチケット化する。

### 開発方針（重要）

「初めてのローカルLLM開発を、実機スペックで実現可能性を評価しながら進める」ため、企画書の最終形をいきなり作らず段階的に進化させる。

1. **評価フェーズはPython優先** — まず Python（uv/ruff）で価値とモデル性能を素早く検証し、**速度が問題になったホットパスだけ後からRustへ移植**する。
2. **バッチMVPから段階的にリアルタイム化** — 中核価値（録音→文字起こし→要約→Markdown）をバッチCLIで立ち上げてから、リアルタイム化・話者識別・協調UIを積む。
3. **各フェーズに定量的な合否基準（評価指標）を置く** — RTF / CER / tok/s 等を実測して判断する。

**現在地: Phase 0（評価基盤・性能スパイク）** — このPCでローカルLLM/STTが実用速度で動くかをベンチマーク中。

## プロジェクト固有の設定

### 技術スタック

段階的に進化させるため、**評価期（現在）**と**製品期（最終形）**で構成が異なる。

- **評価期（現在 / Python）**: faster-whisper（STT）/ Ollama + Qwen（要約）/ sounddevice（収音）/ CLI / ruff
- **製品期（最終形 / Rust）**: whisper-rs（STT）/ Ollama（要約）/ ONNX Runtime（話者識別）/ cpal（収音）/ Tauri + TypeScript + Yjs/CRDT（UI）
- **動作環境**: Windows 11 / GPUなし（CPU駆動, AVX-512活用）/ RAM 59.7GB（うち利用可能は実測で変動し、要約モデル選定に影響）
- **AI**: すべてローカル実行（話者識別・STT・LLM要約）— クラウド送信なし（完全オフライン）

> 詳細な技術選定（評価期↔製品期の対応）は `doc/plan/開発ロードマップ.md` §7 を参照。

### コーディング規約
- 詳細: `doc/templates/coding-standards.md`（コーディング基準書）
- コードレビュー時はこの基準書に基づいて評価する

### テスト方針
- 単体テストは pytest（評価期）。
- ローカルLLM/STTの性能は `doc/plan/開発ロードマップ.md` §5 の評価指標（RTF / CER / tok/s / E2E遅延 等）を実測して判断する。

### セキュリティ要件
- 機密情報の外部送信禁止。AI処理は完全ローカルで完結すること。
