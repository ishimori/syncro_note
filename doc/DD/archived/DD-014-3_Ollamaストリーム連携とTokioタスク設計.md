# DD-014-3: Ollama ストリーム連携と Tokio タスク設計・バックプレッシャ

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-09 | 見送り（親DD-014で凍結・2026-06-09アーカイブ） |

> 親: [DD-014（P4-3 ホットパス Rust 移植）](DD-014_P4-3ホットパスRust移植_cpal_whisper-rs_Tokio.md) ／ アプローチ: 標準（並行設計）
> 依存: [DD-014-2](DD-014-2_whisper-rs統合とAVX512ビルド検証.md)

## 目的

reqwest async で Ollama `/api/chat` ストリーミング連携を実装し、**Tokio 4タスク（T_audio/T_stt/T_clean/T_state）**とチャネル容量・backpressure・劣化戦略を完成させる。

## 背景・課題

- Ollama は client 側 abort でも server が生成継続する既知挙動（親DD起票時DA#3）。`num_predict` 上限＋`keep_alive:0`＋`/api/ps` 空確認で制御（基本設計書 §3.4・DD-006 実測）。
- STT/LLM 時間分離既定。合計が物理8コアを超えないよう whisper threads ≤4 ＋ Ollama num_thread ≤3。

## 検討内容

**スコープイン**
- reqwest async による Ollama `/api/chat` ストリーミング連携
- Tokio 4タスク（T_audio/T_stt/T_clean/T_state）分離設計
- チャネル設計（ringbuf SPSC + tokio mpsc bounded(8)/bounded(4)）と backpressure
- 劣化戦略（同話者連結[speaker_id一致 && 時間差<500ms] → LLMバイパス → 生テキスト即表示）
- Ollama stream の中断制御（num_predict上限 + keep_alive:0 + /api/ps空確認）と timeout guard

**スコープアウト（重複回避）**
- 清書(gemma4)/ライブ整形(qwen3)の**機能仕様**自体 → DD-012-2 / DD-012-4
- モデル切替シーケンスの実測 → DD-006（完了済）を参照のみ
- UI への最終 emit 配線 → DD-014-4
- whisper-rs 本体 → DD-014-2
- **未決事項**: Rust での LLM パイプライン統合時のメモリ/キャッシュ戦略（live常駐 vs batchオンデマンドの型設計）を本DDに含めるか別子にするか

## 決定事項

- 通信・タスク基盤に集中（機能仕様は参照のみ）。劣化時は「原文を真実源とする」原則を貫き生テキスト即表示。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 対象ファイル明記（Tokio タスク・チャネル・reqwest クライアント）
- [ ] 📐 実装前詳細化トリガー判定（並行処理・backpressure・トランザクション境界 → **詳細化要**）
- [ ] 😈 Devil's Advocate（deadlock/race・stream hang・backpressure 設計）

### Phase 1: Tokio 4タスク＋Ollama stream＋backpressure
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] 4タスク分離・bounded チャネル・劣化戦略・timeout guard を実装
- [ ] 🔬 機械検証: backpressure が機能／stream timeout時に keep_alive:0 で hang 回避／オーバーフロー時に生テキスト即表示
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-014 の子・未実装）。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase N DA批判レビュー
（着手時に記録）
