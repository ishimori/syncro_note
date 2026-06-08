# DD-014-1: cpal 収音→ringbuf→VAD チャンク化（音声フロント）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-09 | 見送り（親DD-014で凍結・2026-06-09アーカイブ） |

> 親: [DD-014（P4-3 ホットパス Rust 移植）](DD-014_P4-3ホットパスRust移植_cpal_whisper-rs_Tokio.md) ／ アプローチ: 標準（探索的実装・実機ベンチ）
> 前提: [DD-011](DD-011_Phase4_Tauri2ペインUI骨格_Python中身に接続.md) ／ DD-010（Python準リアルタイムの基準）

## 目的

cpal（WASAPI）で **16kHz mono PCM** をキャプチャし、lock-free SPSC **ringbuf** へバッファリング、**Silero VAD（ONNX）**で無音検出して最大 8〜12s チャンク化する「音声フロント」を Rust で実装する。Python サイドカー収音を Rust ネイティブへ置換する移植の最初の一切れ。

## 背景・課題

- cpal の data callback は **OS RT スレッド**。alloc / lock / log 禁止（stack safe のみ）。オーバーフロー時は drop カウンタで追跡、次フレームでリカバリ。ここがRust移植の最難関の一つ。

## 検討内容

**スコープイン**
- cpal による 16kHz mono PCM キャプチャ（WASAPI on Windows）
- ringbuf（lock-free SPSC）への音声バッファリング
- Silero VAD（ONNX Runtime）による無音検出＋最大 8〜12s チャンク化
- data callback の RT制約遵守（alloc/lock/log 禁止）／ drop カウンタ追跡＋次フレームリカバリ

**スコープアウト（重複回避）**
- whisper-rs STT 本体 → DD-014-2
- Ollama LLM 連携 → DD-014-3
- Python サイドカー経由のマイク結線 → DD-012-1 が持つ既存実装
- UI への token emit → DD-014-4

## 決定事項

- 収音は cpal ネイティブ。VAD は ONNX（Silero）。実機計測を合否基準にする。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 対象ファイル明記（`app/src-tauri/` の音声モジュール・依存追加）
- [ ] 📐 実装前詳細化トリガー判定（新規依存＋RTスレッド並行処理 → **詳細化要**）
- [ ] 😈 Devil's Advocate（RT callback の罠・ringbuf 容量・VAD レイテンシ）

### Phase 1: cpal収音→ringbuf→VAD
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] cpal収音・ringbuf・Silero VAD チャンク化を実装
- [ ] 🔬 機械検証（実機）: 3〜5分連続でドロップ0・キューオーバーフロー0、callback内に alloc/lock/log が無い
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-014 の子・未実装）。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase N DA批判レビュー
（着手時に記録）
