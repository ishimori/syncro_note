# DD-004-1: ONNX話者埋め込みによる高精度話者分離の評価と採用確定

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 進行中 |

> 親DD: [DD-004](DD-004_話者分離PoC_日本語オフライン一括ラベリングのCPU評価.md)（評価ハーネス＋baseline を確立済み）。
> アプローチ: 標準（探索的実装＝性能/精度スパイク）。本DDで**評価期に採用する話者分離手法を確定**する。

## 目的

DD-004 で作った評価基盤（[参照RTTM自動生成・自前DER・simple-clusterベースライン](DD-004/結果.md)）を使い、
**本命の「ONNX話者埋め込み（speaker embedding）」系手法**を実装・比較して、評価期に採用する話者分離手法を1つ確定する。

## 背景・課題

- DD-004 の baseline `simple-cluster`（手作りMFCC特徴＋KMeans）は易しいケースで DER 0.036 だが、**"何を喋ったか"に引っ張られやすく**雑音・人数増・声の被りに弱い見込み。
- 本命は **訓練済みAIが声の指紋（埋め込みベクトル）を作る**方式（ECAPA-TDNN / 3D-Speaker 等）。"誰の声か"を直接捉え、ロバスト。**ONNX形式でCPU・オフライン実行**でき、製品期 Rust（ONNX Runtime `ort`）と地続き（[基本設計書 §6/§9](../spec/基本設計書.md)）。
- 最大の関門は **完全オフライン要件との整合**（モデル入手・初回DL・ライセンス）。

## 検討内容（候補と評価軸）

| 候補 | 概要 | オフライン適合 | 製品Rust移植 |
|------|------|---------------|-------------|
| **sherpa-onnx** | ONNX前提の話者埋め込み＋VAD。Apache。モデル自由DL | ◎（DL後は完全ローカル） | ◎（ONNX共通） |
| **pyannote.audio** | 定番・高精度の一体パイプライン | △（HF gated・初回DLにネット＋規約承認） | △（PyTorch系） |
| **自作**（Silero VAD＋ECAPA/3D-Speaker ONNX＋クラスタリング） | 依存最小・透明 | ◎ | ◎ |

**評価軸**: DER / 話者数推定精度 / RTF / 導入難度 / **オフライン適合**（初回DL・ライセンス）/ 製品Rust移植性。
評価素材・正解RTTM・DER計測は **DD-004 のハーネスをそのまま流用**（`diarize(audio, sr)->list[Turn]` 互換アダプタとして各手法を実装）。

## 決定事項

（評価後に確定）採用手法・パラメータ・製品期移植方針をここに記録する。現時点で未確定。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 タスク精査・詳細化（対象パス・🔬機械検証の明記）
- [x] 📐 詳細化トリガー判定（新規依存・新規モジュール → 詳細化要と判定）
- [x] 😈 Devil's Advocate（下記表）。**最重要=オフライン制約の実地確認** → CAM++はgateなし・初回DLのみネット・以降オフラインで **PASS**（[結果](DD-004-1/結果.md)）

### Phase 1: 依存導入と本命1手法の疎通
- [x] 📐 実装前詳細化（ユーザー方針「ベストエフォートで実装まで」に従い、設計決定を記録のうえ実装）
- [x] 依存導入: `onnxruntime`(既存1.26.0) ＋ **`kaldi-native-fbank`** を `uv add`（UI停止後・pyproject干渉なし）。⚠️**sherpa-onnx wrapper はORT版数不整合で不可** → onnxruntime直接実行へ切替（[結果](DD-004-1/結果.md)）
- [x] モデル入手: CAM++(sherpa-onnx配布)をDLしローカルキャッシュ。ネット要否・ライセンスを実地記録（初回DLのみ・Apache・gateなし）。モデルは `models/` でgit管理外＋手順を `models/README.md` に
- [x] `diarization/embedding_onnx.py` 新規: VAD→knf fbank→CMN→CAM++→L2埋め込み→KMeans を `diarize` I/Fで実装、`METHODS` に `onnx-embed` 登録
- [x] 🔬 機械検証: `diarization_bench ... --method all` で DER 出力。**onnx-embed 0.047 / simple-cluster 0.036**（easy素材で実質互角）。ruff通過・pytest 56 passed
- [x] 😈 DA批判レビュー: 「easy素材ではbaselineと差が出ず本命の優位を判定できない」→ 採用確定は被り有り/多話者素材が前提、と明記

### Phase 2: 候補比較
- [x] onnx-embed（CAM++）と simple-cluster を sample02 で DER/RTF 比較（[結果](DD-004-1/結果.md)）
- [→] pyannote / 多言語埋め込みモデルの追加比較は **後続**（オフライン制約を満たす範囲で。pyannoteはgated要確認）
- [x] 結果を [`DD-004-1/結果.md`](DD-004-1/結果.md) に表で記録
- [x] 🔬 機械検証: 表が欠測なく揃う／ruff・pytest 緑
- [x] 😈 DA批判レビュー: sherpa-onnx wrapper のORT不整合という統合リスクを実地で発見・回避策を記録

### Phase 3: 採用確定と SSOT 反映（DD-004系列のクローズ）
- [ ] 評価期に採用する手法（とフォールバック）を決定し「決定事項」に記載
- [ ] [基本設計書 §9](../spec/基本設計書.md) の DD-004 行を「採用=○○（結果リンク）」へ更新（⚠️ DD-006 行と隣接。**DD-006セッションと同時編集を避ける**）
- [ ] [開発ロードマップ §8/Phase 3](../plan/開発ロードマップ.md) に採用結果を反映
- [ ] 🔬 機械検証: `bash scripts/doc-index-check.sh --strict` exit 0
- [ ] 😈 DA批判レビュー（最低1件）

> ⏸️ **後回し継承**: オーバーラップ・3〜4話者の追加素材での劣化測定／話者数自動推定は、複数人音声の準備が整い次第（DD-004 から引き継ぎ）。本DDの一次比較は sample02 ベースで進める。

## ログ

### 2026-06-07
- 親DD-004（ハーネス＋baseline確立）から分割して起票。本命ONNX埋め込み手法の評価と採用確定を担当。評価基盤はDD-004を流用。
- Phase 0–1 実施。オフライン制約PASS（CAM++はgateなし・初回DLのみ）。sherpa-onnx wrapper はORT版数不整合で不可→onnxruntime直接＋kaldi-native-fbankへ切替。`onnx-embed` 実装し DER 0.047（baseline simple-cluster 0.036 と easy素材で実質互角）。pytest 56 passed。**採用確定(Phase 3)は被り有り/多話者素材待ち＝進行中のまま**。詳細 [結果](DD-004-1/結果.md)。

---

## DA批判レビュー記録

<!-- 手順・品質フィルターは doc/da-method.md を参照 -->

### Phase 0 DA批判レビュー

**DA観点:** 完全オフライン要件（機密の社外送信禁止）に、どの候補が本当に適合するか。ここを外すと採用後に手戻り。

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | pyannote はモデルがHF gated＝初回DLにネット必須＋規約承認。完全オフライン運用・再配布で詰む可能性 | 高 | 初回 `from_pretrained` でネット/トークン要求 | 制約整合性 | Phase 1 で実地確認。抵触なら sherpa-onnx/自作を優先 |
| 2 | onnxruntime CPU で実用RTFに収まらない／AVX-512を活かせない可能性 | 中 | 120s音声で RTF 測定 | 性能前提 | Phase 1 で RTF 実測。終了後バッチ用途なら RTF≥1 も許容 |
