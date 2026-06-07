# DD-014-2: whisper-rs STT 統合と AVX-512 ビルド検証

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 未着手（DD-014-1 後 / SIMD検証は前倒し可） |

> 親: [DD-014（P4-3 ホットパス Rust 移植）](DD-014_P4-3ホットパスRust移植_cpal_whisper-rs_Tokio.md) ／ アプローチ: 標準（実機ベンチ）
> 依存: [DD-014-1](DD-014-1_cpal収音とringbufとVADチャンク化.md)

## 目的

whisper-rs（whisper.cpp binding）を統合し、**n_threads=4・AVX-512 有効化を確認**したうえで、VAD チャンクを STT にかけて Python 版（DD-010）と RTF/遅延を比較する。

## 背景・課題

- AVX-512 が有効化されないとチューニング効果が0で性能目標未達（親DDの起票時DA#1）。`cargo --release`/RUSTFLAGS の設定と `objdump -d | grep -i avx512` での検証が要。**着手前倒し（early action）**で先にビルド検証する。
- STT/LLM 時間分離既定（基本設計書 §1 原則6）。whisper threads ≤ 4。

## 検討内容

**スコープイン**
- whisper-rs 統合・n_threads=4 設定
- AVX-512 有効化確認（`objdump -d | grep avx512`。early action）
- spawn_blocking による CPUバウンド（whisper-rs）の専用 pool 化
- DD-010（Python: RTF≈0.527 / E2E≈4s）との RTF/E2E 遅延比較ログ

**スコープアウト（重複回避）**
- cpal収音・VAD → DD-014-1
- Ollama LLM 連携 → DD-014-3
- DB 書込み → DD-012-3 の Rust単独所有原則に従い T_state へ集約（DD-014-4）
- 話者埋め込み ONNX 本体 → DD-004-1（別セッション）

## 決定事項

- ビルドが AVX-512 を含むことを `objdump` で機械確認してから性能評価に進む。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 対象ファイル明記（whisper-rs 依存・STT モジュール・ビルド設定）
- [ ] 📐 実装前詳細化トリガー判定（新規依存＋性能特性 → **詳細化要**）
- [ ] 😈 Devil's Advocate（AVX-512未有効・Windows binding の不完全さ）

### Phase 1: AVX-512 ビルド検証（前倒し）
- [ ] whisper-rs を release ビルドし `objdump -d | grep -i avx512` で SIMD 有効化を確認
- [ ] 🔬 機械検証: AVX-512 命令が含まれる

### Phase 2: STT 統合＋RTF比較
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] VADチャンクを whisper-rs で文字起こし、spawn_blocking pool 化
- [ ] 🔬 機械検証: RTF が DD-010 比 15%以上改善の見込みを実測ログで確認
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-014 の子・未実装）。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase N DA批判レビュー
（着手時に記録）
