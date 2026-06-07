# DD-008: バッチMVP（音声ファイル → 議事録Markdown）

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 完了 |

> アプローチ: 標準（探索的実装）。ただし辞書ケバ取り等の純粋ロジックは TDD で検証する。初の「中核価値の実装」DD。
> ロードマップ対応: [開発ロードマップ.md](../plan/開発ロードマップ.md) **Phase 1 / P1-1〜P1-3**。設計の正は [基本設計書.md](../spec/基本設計書.md)。前提実測は [DD-002](DD-002_LLM生成速度ベンチマーク.md)（要約LLM）/ [DD-003](DD-003_STT実機ベンチと同時実行スパイク.md)・[DD-005](DD-005_whispercpp実RTFクロスチェックと実VAD検証.md)（STT/VAD）。
>
> 【位置づけ】評価期の部品検証（DD-002/003/005）を**1本のバッチパイプラインに統合**し、初めて**議事録としての品質**を評価する。リアルタイム化・話者識別・UI・DBは扱わない（製品期 / 他DD）。

## 目的

中核価値「**音声ファイル → 文字起こし → 要約 → Markdown議事録**」を Python CLI で最短E2E動作させ、生成された議事録の**品質**（要約・決定事項・TODO の網羅性/正確さ）を [ロードマップ §5 ルーブリック](../plan/開発ロードマップ.md) で評価する。

## 背景・課題

- Phase 0（DD-002/003/005）で**速度・精度の部品**は検証したが、**最終議事録の品質は未評価**。「gemma4:26b が実際に良い議事録を書くか」が最大の未知。
- 中核価値はリアルタイム/話者識別/UI/CRDT に依存しない。まずバッチで立ち上げて品質を測り、以降の投資判断材料にする（ロードマップ基本方針2）。
- 製品期の UI（mock）・DB（DD-007）とは独立。本MVPは **DB無し・file in → markdown out**。

## 検討内容

**パイプライン（設計SSOT準拠）**
```
音声file → 16kHz mono化 → VAD(無音除去: 幻覚抑制) → faster-whisper(medium, ja)
  → 生タイムライン → 辞書＋正規表現ケバ取り → Ollama要約(gemma4:26b) → 議事録Markdown → file出力
```
- **VAD必須**（DD-005: 無音で whisper が幻覚 → 有声だけ渡す）。`vad_segment.detect_voiced_spans` を再利用。
- **STTは medium**（DD-003/005: 日本語精度に必要）。`stt_bench` の `_load_audio`/`_transcribe` を再利用。
- **ケバ取りは辞書＋正規表現**（LLM整形に頼らない）。フィラー（えー/あの/まあ 等）除去＋専門用語辞書置換（Tauri/SQLite/人名 等）。純関数でTDD。
- **要約はバッチLLM**（gemma4:26b。`llm_bench` の SUMMARY_INSTRUCTION を議事録構造化に拡張: 要約/決定事項/TODO）。
- 話者分離は本MVPでは扱わない（単一話者前提 or 話者ラベルなし）。

**評価**: DD-005 の `audio/sample01.wav`（と任意で実会議音声1本）でE2E。議事録品質を §5 ルーブリックで人手評価し所感を残す。

**既存資産の再利用/昇格**: `bench/` の検証コードから本番パイプライン `pipeline/`（または `mvp/`）へ必要部を昇格。重複は最小化。

## 決定事項

- パイプラインを `python/src/synchroni_note/pipeline/` に実装。CLIエントリ `synchroni-note transcribe <audio> --out <md>`（pyproject の scripts に登録）。
- 辞書ケバ取りは純関数（フィラー除去・用語置換）として `pipeline/cleaning.py` に実装し pytest で検証。
- 要約プロンプトは議事録3セクション（## 要約 / ## 決定事項 / ## TODO）を強制。
- 成果物（生成議事録サンプル＋品質評価）を `doc/DD/DD-008/` に残す。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 各Phaseのタスク精査（対象パス・具体的変更・🔬機械検証が揃っているか）
- [x] 📐 実装前詳細化トリガー判定
  - 規模シグナル: 新規モジュール（pipeline）＋CLIエントリ追加に該当。
  - 複雑度シグナル: 外部I/O（whisper/Ollama）はあるが各部品は検証済み。並行処理・DB・セキュリティ境界なし。
  - 判定結果: **Phase 1/2 → 詳細化不要**（部品はDD-003/005で実証済み、純関数はTDD）。
  - 実装メモ: VADは faster-whisper 内蔵 `vad_filter=True`（Silero）を採用（評価期エンジンに最適・タイムスタンプ保持）。`vad_segment.py` は whisper.cpp 用 proxy として残す。
- [x] 😈 Devil's Advocate調査
  - 要約が長文入力で num_ctx 超過 → 長尺は分割（map-reduce）要否を品質評価で判断。
  - 辞書置換の誤爆（部分一致で別語を壊す）→ 単語境界/優先順位を設計。
  - バッチMVPは話者なし → 「誰が言ったか」が要る議事録で物足りない可能性（話者は後続DD）。

### Phase 1: STT＋VAD段（音声 → 生タイムライン）
- [x] `pipeline/__init__.py` / `pipeline/transcribe.py` 作成: file → faster-whisper(medium) ＋ **`vad_filter=True`（Silero内蔵）** → `Segment(text, t_start_ms, t_end_ms)` 列。`transcript_text` で連結
- [x] 🔬 機械検証: `sample01.wav` から**無音幻覚なし**の生テキスト（8セグメント/233文字）が出る
- [x] 😈 DA批判レビュー（最低1件）

### Phase 2: ケバ取り＋要約段
- [x] `pipeline/cleaning.py`: フィラー除去＋専門用語辞書置換（純関数・**単一パス正規表現**）。`tests/test_cleaning.py`（8ケース）
- [x] `pipeline/summarize.py`: ケバ取り済みテキスト＋語彙/アジェンダ → Ollama(gemma4:26b) → 議事録Markdown（## 要約/## 決定事項/## TODO）
- [x] 🔬 機械検証: `uv run ruff check .` / `uv run pytest -q` 緑（37 passed）。要約出力が3セクション構造
- [x] 😈 DA批判レビュー（最低1件）

### Phase 3: CLI統合・E2E・品質評価
- [x] CLI `synchroni-note transcribe <audio> --out <md>` に統合（pyproject `[project.scripts]` 登録、stdout UTF-8化）
- [x] `sample01.wav` でE2E実行し議事録Markdownを生成（gemma4:26b ＋ qwen3:8b 比較）
- [x] §5 ルーブリックで品質を人手評価し `doc/DD/DD-008/結果.md` に記録（gemma4:26b 4.5 / qwen3:8b 3.5 → batch=gemma4:26b 採用）
- [x] 🔬 機械検証: 1コマンドで音声→議事録Markdownがエラーなく生成（exit 0）
- [x] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-07
- DD作成。
- 同セッションで Phase 0〜3 を一気通貫実装（ユーザー離席中・ベストエフォート）:
  - `pipeline/`（transcribe / cleaning / summarize / cli）新設。CLI `synchroni-note transcribe` を登録。
  - Phase 2 で用語置換の**誤爆バグをDA発見→単一パス正規表現に修正**（test_apply_vocab_longest_key_first）。
  - **E2E成功**: sample01.wav → 8セグメント文字起こし(medium+VAD) → ケバ取り → gemma4:26b要約 → 議事録Markdown。**VADで無音幻覚ゼロ**。
  - 品質: gemma4:26b ◎(4.5)／qwen3:8b ○(3.5) → **batch=gemma4:26b 採用**（DD-002選定を品質面でも追認）。
  - 確認: **専門用語ヒントで要約側が用語誤りを補正**（TOWERY/SQライト→Tauri/SQLite）。
  - ruff緑・pytest 37 passed。生成議事録は `doc/DD/DD-008/議事録_sample01.md`（＋qwen8b版）。
  - cp932端末で `✓` 出力がクラッシュ→CLIで stdout を UTF-8 再構成して修正。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー

**DA観点:** （STT＋VAD段が無音幻覚なく安定して生テキストを出すか）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | 本MVPのVADは **faster-whisper 内蔵 `vad_filter`（Silero）依存**。製品エンジン whisper.cpp(whisper-rs) には無いため、製品移植時は別VAD（DD-005の `vad_segment` or Silero ONNX）が必要。評価期と製品期でVAD実装が分かれる。 | 中 | whisper.cpp 経路では vad_filter が使えない | エンジン差（VADの所在） | 評価期は内蔵VADで十分。製品期はRust側にSilero ONNX等を実装（基本設計§5/§3.4）。本MVPの位置づけ=評価期と明記。 |

### Phase 2 DA批判レビュー

**DA観点:** （ケバ取りの誤爆・要約プロンプトの頑健性）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | **用語置換の誤爆バグを実装中に発見**: 逐次 `str.replace` だと「要約モデル→…」置換後のテキストに短いキー「要約」が再マッチして壊れる。 | 中 | `apply_vocab("要約モデルの話", {"要約":"X","要約モデル":"Y"})` が想定外に | 置換ロジックの正しさ | ✅修正済: **全キーを長い順の単一パス正規表現**で置換（再スキャンなし）。test_apply_vocab_longest_key_first で固定。 |
| 2 | DEMO_VOCAB は**エンジン固有の誤認識**に依存（whisper.cpp由来の「ハウリ/スキューライト」）。faster-whisper は別の誤り（TOWERY/SQライト）を出し辞書が当たらない。 | 中 | faster-whisper 出力に DEMO_VOCAB が空振り | 辞書の汎用性 | 運用で実誤認識を辞書化。加えて**要約LLMへ正用語をヒント**として渡すと要約側で補正される（本MVPで有効性確認）。 |

### Phase 3 DA批判レビュー

**DA観点:** （E2E議事録の品質評価が妥当か）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | 品質評価が**単一・短尺・単一話者の1サンプル**のみ。実会議（長尺・複数話者・雑音）の品質は未確認で、4.5という評点を一般化できない。 | 中 | 別音声で再評価すると評点が変動 | 評価サンプルの代表性 | 複数サンプル（特に実会議音声）で評価拡充。本DDは「中核が動く＋単一サンプルで高品質」を確認する位置づけ。 |
| 2 | 話者帰属（TODO担当=佐藤 等）は**話者分離なしのLLM推測**で、誤帰属しうる。qwen3:8b版では帰属が増え精度も不安定。 | 中 | 別の発話順で担当が入れ替わる | 帰属の信頼性 | 話者分離（DD-004）導入で帰属精度を上げる。MVPでは「推測」と割り切り、人間補正前提（設計のT4）。 |
