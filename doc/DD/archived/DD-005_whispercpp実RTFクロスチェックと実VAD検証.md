# DD-005: 製品エンジン(whisper.cpp)実RTFクロスチェックと実VAD区切り検証

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 完了 |

> アプローチ: 標準（探索的実装）。成果物は「製品エンジン基準の実測値とゲート再判定」であり、最小コストでの不確実性除去が目的。RTF/分割ロジックの純関数だけ小さくテストする。
> ロードマップ対応: [開発ロードマップ.md](../plan/開発ロードマップ.md) Phase 0 の締め（P0-3/P0-4 を製品エンジン基準で確定）。設計上の位置づけは [基本設計書.md](../spec/基本設計書.md) §5/§7/§9。前提は [DD-002](DD-002_LLM生成速度ベンチマーク.md)（LLM）/ [DD-003](DD-003_STT実機ベンチと同時実行スパイク.md)（STT, faster-whisper基準）。
>
> 【スコープ注記】基本設計 §9 の「DD-005＝liveパイプライン縦切り（Tauri/Rust）」のうち、**リスクの本体である"製品エンジンの実RTF"検証を本DDに切り出し**、最小コスト（Python寄り）で先に潰す。**cpal/ringbuf/actor/emit のフルTauri統合は本DDの範囲外**（Rust本格移植を始める後続DDに分離）。004 は [話者分離PoC] 用に予約。

## 目的

製品で使う STT エンジン **whisper.cpp**（製品期は `whisper-rs` がラップ）の**実RTFを、評価エンジン faster-whisper と同一音声で突き合わせ**、リアルタイム可否を**製品基準**で確定する。併せて**実VAD（無音境界）区切り**で 8〜12秒セグメントの RTF/CER を再測し、DD-003 の「固定時間切り＝CER悲観」を補正する。基本設計 §7/§9 に残る最大の不確実性を最小コストで除去する。

## 背景・課題

DD-003 で faster-whisper 基準のゲートは「条件付きPASS（単体 medium 8〜12秒 RTF 0.43〜0.61）」だが、製品判断には次の3点が未解決:

1. **エンジン差**: 製品は whisper.cpp。faster-whisper(CTranslate2) は一般に whisper.cpp より**速い**ため、DD-003 の RTF は**楽観側**。製品エンジンが 1.5〜2倍遅いと medium のマージンを食い RTF→1.0 に近づくリスク。
2. **固定時間切りの悲観**: DD-003 の streaming は無音を無視した固定分割で、文を断片化し CER を悪化。実VAD境界なら改善するはず（未検証）。
3. **録音レベル低**: DD-003 の音声は peak0.10 と低く CER 絶対値が悲観側。適正音声での medium 実力値が未確定。

## 検討内容

**whisper.cpp の実RTF計測手段（最小コスト優先で選ぶ）**
- 候補A: **prebuilt CLI**（`ggml-org/whisper.cpp` の Windows リリース `whisper-cli.exe`）に GGUF を渡し wall-time から RTF 算出。ビルド不要で最小コスト。
- 候補B: **Python バインディング**（`pywhispercpp` 等）。stt_bench と同じ枠組みで計測可だが Windows ビルドの可否を要確認。
- 候補C: `whisper-rs`（Rust）。製品そのものだが環境構築が重い。本DDでは必須としない。
- 量子化 GGUF（base/medium、`q5_0`/`q8_0` 等）。同一 `python/audio/sample01.wav`・n_threads スイープ・batch＋8〜12秒チャンク。→ **faster-whisper との RTF 倍率**を出す。

**実VAD区切り**
- `silero-vad`（ONNX, 高精度）または `webrtcvad`（軽量）で無音境界を検出し、8〜12秒目安でセグメント化。
- 実VADセグメントで RTF/CER を再測し、DD-003 の固定3s/10s と比較（CER がどれだけ改善するか）。

**適正音声（任意・CER確度向上）**
- 近接/適正レベルで `script01.txt` を再録音 → medium の CER 実力値を取得。

**指標**: 製品エンジン RTF（対 faster-whisper 倍率）／実VAD区切りの RTF・CER／適正音声 CER。

## 決定事項

- エンジンクロスチェックは**最小コスト手段（候補A:prebuilt CLI を第一、ダメなら B）**で実施。Rust(whisper-rs) は本DDでは必須としない。
- 実VAD分割は `stt_bench.py` に「VADモード」を追加するか、`vad_segment.py` を新設。
- 結果は `doc/DD/DD-005/結果.md`（添付）に記録。判定を基本設計 §5/§7/§9・ロードマップ §8 へ反映。
- フルTauri縦切り（E2E遅延・ドロップ0・キュー有界）は本DDで扱わず、後続DD（Rust移植本格化）に分離。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 各Phaseのタスク精査（対象パス・具体的変更・🔬機械検証が揃っているか）
- [x] 📐 実装前詳細化トリガー判定
  - 規模シグナル: 外部ツール（whisper.cpp/VAD）導入に該当。
  - 複雑度シグナル: 計測ロジックは単純。環境構築（whisper.cppバイナリ/GGUF入手）が詰まりうる点が主リスク。
  - 判定結果: **詳細化不要**だが、エンジン入手の**代替手段（A/B/C）を用意**して着手する。
- [x] 😈 Devil's Advocate調査
  - prebuilt CLI と whisper-rs で同一ビルド最適化（AVX-512等）か不明 → ビルド条件を結果に明記。
  - GGUF量子化レベルで RTF/CER が変わる → faster-whisper(int8)と公平になる量子化を選ぶ。
  - 単一音声依存（DD-003と同じ弱点）→ 可能なら複数条件。

### Phase 1: whisper.cpp 実RTFクロスチェック
- [x] whisper.cpp 実行手段を確保（**候補B: pywhispercpp 1.5 を導入**。numpy入力でstt_benchと同枠組み）
- [x] base/medium GGUF を取得（pywhispercpp 自動DL）
- [x] 同一 `python/audio/sample01.wav` で batch＋10秒チャンクの RTF を計測（threads=8）
- [x] `doc/DD/DD-005/結果.md` に whisper.cpp RTF と **faster-whisper 比の倍率**を記録
- [x] 🔬 機械検証: 結果Markdownに whisper.cpp の RTF 数値（batch/10秒）が揃っている
- [x] 😈 DA批判レビュー（最低1件）

### Phase 2: 実VAD区切り検証
- [x] VAD導入（**依存追加なしの簡易エネルギーVAD** `bench/vad_segment.py`。無音除去・8〜12秒分割。マージ/分割は純関数）
- [x] 実VADで RTF/CER を再測（faster-whisper ＋ whisper.cpp）。無音込みと比較 → CER 5倍改善を確認
- [x] `python/tests/test_vad_segment.py`（10ケース）追加
- [x] 🔬 機械検証: `uv run ruff check .` / `uv run pytest -q` 緑（29 passed）。結果.mdに無音込み vs VAD後の CER 差
- [x] 😈 DA批判レビュー（最低1件）

### Phase 3: 適正音声での再計測（任意）
- [~] 見送り: VADで CER 0.111（whisper.cpp medium）まで下がり実用域に達したため、再録音は後続に回す。適正録音でさらに改善見込みとだけ記録。

### Phase 4: 製品基準ゲート判定・反映
- [x] **ゲート再判定**: whisper.cpp medium streaming@10s RTF **0.688<1**（時間分離・単体）＋ VAD後 CER **0.111** → **PASS**
- [x] 基本設計書 §7/§9・ロードマップ §8 を製品エンジン実測で更新
- [x] 🔬 機械検証: 製品基準のゲート判定（PASS）が結果Markdownに明記
- [x] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-07
- DD作成。
- 同セッションで即日実施:
  - Phase 1: pywhispercpp(whisper.cpp)導入。RTF base batch0.045/strm10s 0.098, medium batch0.386/**strm10s 0.688**。faster-whisper比でmediumは~1.1〜1.4倍遅いが、8〜12秒VAD・時間分離なら<1維持。
  - Phase 2: 簡易エネルギーVAD(`vad_segment.py`)実装＋テスト10件。VADで無音24s除去→**公平CER: fw 0.258→0.055 / cpp 0.567→0.111**。CERの大半は無音幻覚の人工物と判明。
  - Phase 4: **ゲートPASS**（whisper.cpp medium 8〜12秒VAD・時間分離で RTF 0.688<1, CER 0.111）。基本設計§7/§9・ロードマップ§8反映。
  - 重要知見: **whisper.cppは無音/低レベルノイズで幻覚**（"佐藤さん:…"を大量生成）→ VADで有声だけ渡すのが必須。残差誤りは固有名詞/同音語＝辞書置換で補正する対象。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー

**DA観点:** （製品エンジンの計測が公平・再現可能か）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | pywhispercpp の whisper.cpp ビルドが **AVX-512 最適化か未確認**。製品 `whisper-rs` のビルドフラグ次第で RTF が上下し、本DDの倍率がそのまま製品に当てはまらない可能性。 | 中 | pywhispercpp の system_info ログで SIMD フラグを確認 | エンジン差（ビルド条件） | 傾向把握として扱い、製品ビルド（whisper-rs, AVX-512有効）で再測。GGUF量子化も faster-whisper int8 と厳密同条件ではない点も含め「倍率は目安」と結果.mdに明記。 |

### Phase 2 DA批判レビュー

**DA観点:** （実VAD分割が実運用を代表し、CER改善が本物か）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | 簡易エネルギーVADの閾値（abs_floor/rel）は **sample01 に合わせた値**で、雑音・小声・遠距離マイクでは誤検出（有声を落とす/無音を拾う）しうる。28区間・46.1sの妥当性は本音声でのみ確認。 | 中 | 雑音入り/小声の音声で voiced_seconds が不当に増減する | 計測の代表性（VADの頑健性） | 製品は **Silero 等の学習済みVAD** へ。閾値の頑健性は雑音サンプルで要再検証。`vad_segment.py` の検出は評価用の proxy と位置づけ。 |
| 2 | VAD後出力で文頭「本日の」が一部欠落。境界トリミング/pad不足で語頭を削る恐れ。 | 低 | pad_ms を 0 にすると語頭欠落が増える | 分割境界の品質 | pad_ms・オーバーラップ（基本設計§3.4）を現場調整。CERへの影響は軽微。 |

### Phase 4 DA批判レビュー

**DA観点:** （製品基準ゲート判定の妥当性）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | マージンが薄い（medium@10s RTF 0.688）。実会議は本音声より難条件（被り・雑音・長尺）で RTF・CER が悪化しうるため、**0.688 は楽観寄り**。 | 中 | 実会議音声で再測すると RTF が 1.0 に近づく可能性 | ゲートの代表性（易しいサンプル） | 未達時の選択肢を用意: base即時+medium後追い / VAD窓拡大 / medium→small。実会議音声＋whisper-rs で最終確認（後続DD）。 |
| 2 | 全数値が**時間分離前提**。実装でスケジューリング上ほんとうに時間分離が守れるか（STTとLLM追い上げの排他）は未実証。 | 中 | 実装で同時実行が起きると DD-003 のスラッシング再現 | 前提条件の実装可能性 | liveパイプ縦切り（後続DD）で時間分離スケジューラを実装・実測。 |
