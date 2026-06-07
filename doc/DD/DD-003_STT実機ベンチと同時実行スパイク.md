# DD-003: STT実機ベンチとSTT/LLM同時実行スパイク

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-07 | 2026-06-07 | 完了 |

> アプローチ: 標準（探索的実装）。成果物は「実測値と判断材料」であり、安定ロジックの構築が主目的ではないため。RTF/CER算出のような純関数だけ小さくTDD的に検証する。
> ロードマップ対応: [開発ロードマップ.md](../plan/開発ロードマップ.md) の **Phase 0 / P0-3・P0-4**。設計上の位置づけは [基本設計書.md](../spec/基本設計書.md) §7・§9（最優先ゲート）。前提環境は [DD-001](DD-001_環境初期化_uvプロジェクト雛形とruff_pytest.md)、LLM側実測は [DD-002](DD-002_LLM生成速度ベンチマーク.md)。

## 目的

このPC（Ryzen 7 PRO 8840HS / CPU駆動 / AVX-512）で、ローカルSTT（Whisper系）が**日本語の会議音声**をどれくらいの速度（RTF）・精度（CER）で処理できるかをモデル/条件別に実測し、さらに**STTとLLM（qwen3:8b）を同時実行したときのスループット劣化**を測る。これにより [基本設計書](../spec/基本設計書.md) の最優先ゲート「**LLM併走下で per-chunk RTF<1（理想<0.5）を満たすか**」を判定し、リアルタイム議事録の実現性とパイプライン構成（真の並列 vs 時間分離 / live=base or tiny）を確定する。

## 背景・課題

- DD-002でLLM生成速度は実測したが、**STT側のRTF/CERは未測**。リアルタイム議事録の遅延はSTTとLLMの**合算**で決まる。
- 基本設計書は「Whisper確定テキスト即表示を主役／STTとLLMは原則**時間分離**（DDR5帯域律速で同時実行は16〜51%劣化しうる）」とするが、この劣化%と「短チャンク(2〜3秒)streamingのRTF」は**本機実測が必要**。
- faster-whisperは内部で30秒窓にパディングするため、**短チャンクほどRTFが悪化**しうる。streaming前提の可否はここで数字を出さないと判断できない。

## 検討内容

**STTエンジン**
- 評価期方針（ロードマップ§7）に従い **faster-whisper（CTranslate2・CPU最適化）** を使用。
- ⚠️ 製品期は whisper.cpp(whisper-rs) で、RTFは faster-whisper と異なる（一般に faster-whisper の方が速い＝**本DContの値は楽観側**）。製品期で要再測。本DDは「方向性と可否ゲート」を得るのが目的。任意で whisper.cpp 版も stretch で cross-check。

**対象モデル / 条件**
- モデル: `tiny` / `base` / `medium`（large系はCPUで重く除外。余力で `large-v3-turbo` を stretch）。言語=ja, compute_type=int8（CPU既定）。
- スレッド: `cpu_threads` を {4, 6, 8} でスイープ。AVX-512 が効いているかも確認。
- チャンク: **streaming(2〜3秒)** と **batch(30秒/全体)** の両方で計測（短チャンクのRTF悪化を定量化）。

**計測指標**
- RTF = 処理時間 / 音声長（<1 でリアルタイム可）。per-chunk と全体の両方。
- CER = ground-truth との文字誤り率（置換+削除+挿入）/ 参照文字数。
- 初動遅延（最初のセグメント確定までの体感遅延）。

**STT/LLM同時実行スパイク**
- whisper(base) を連続推論で回しながら、DD-002の `llm_bench` で qwen3:8b の tok/s を再測 → **孤立比の劣化%**。
- スレッド総和が物理8コアを超える設定でのスラッシングも観察（whisper n_threads + Ollama num_thread）。
- 既定条件を固定して記録（`OLLAMA_NUM_PARALLEL=1` / `OLLAMA_MAX_LOADED_MODELS=1`）。

**評価用音声（要方針決定）**
- RTF用: 数分の日本語音声があれば足りる（ground-truth不要）。
- CER用: **ground-truth（正解書き起こし）付き**が必要。候補=①公開データ（Common Voice ja / ReazonSpeech 等の小サンプル）②既知スクリプトからTTS生成（正解＝スクリプトだが実会議より楽観）③ユーザー提供の実音声。→ Phase 2 で決定。

## 決定事項

- STTベンチを `python/src/synchroni_note/bench/stt_bench.py` に実装、CLIで実行。RTF/CER算出は純関数に切り出し pytest で検証。
- ランタイム依存に `faster-whisper` を追加。
- 同時実行は既存 `llm_bench` を whisper 併走下で再実行する形で測る（新規実装を最小化）。
- 結果は `doc/DD/DD-003/結果.md`（添付）に表で記録。考察を基本設計書 §7/§9 とロードマップ §8 に反映。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 各Phaseのタスク精査（対象パス・具体的変更・🔬機械検証が揃っているか）
- [x] 📐 実装前詳細化トリガー判定
  - 規模シグナル: 新規モジュール（stt_bench）追加に該当。
  - 複雑度シグナル: 外部I/O(faster-whisper)はあるがロジックは単純。並行処理は「別プロセスを並走させ計測するだけ」でアプリ内並行制御は無し。
  - 判定結果: **Phase 1（harness）→ 詳細化不要**（計測条件は本DDに明記。純関数はテストで担保）。**Phase 2（評価音声の方針）→ 要ユーザー確認**。
- [x] 😈 Devil's Advocate調査
  - faster-whisper の RTF は製品エンジン(whisper.cpp)と乖離 → 本DDは方向性把握、製品期で再測と明記。
  - TTS音声でのCERは実会議より楽観（雑音・被り・なまり無し）→ 可能なら実音声、または雑音重畳も検討。
  - 短チャンク(2〜3秒)は30秒窓パディングでRTF悪化＋文末切れでCER悪化 → streaming戦略の限界を測るのが狙いと明記。
  - 同時実行結果はスレッド設定依存 → 条件固定で記録。

### Phase 1: STTベンチharness構築
- [x] ランタイム依存追加: `python/` で `uv add faster-whisper`
- [x] `python/src/synchroni_note/bench/stt_bench.py` 作成
  - RTF算出の純関数（処理秒, 音声秒 → RTF。0除算ガード）
  - CER算出の純関数（編集距離ベース・空白正規化。参照0長ガード）
  - faster-whisper呼び出し（モデル・cpu_threads・チャンク長を引数化、ja固定、ウォームアップ付き）
  - streaming(2〜3秒分割) と batch(全体) の両モードで処理時間を計測
  - 結果を表形式で標準出力＋Markdown出力
- [x] `python/tests/test_stt_bench.py`: RTF/CER/チャンク分割の単体テスト（既知値・0除算・0長）
- [x] 🔬 機械検証: `uv run ruff check .` / `uv run pytest -q` が緑（18 passed）
- [x] 😈 DA批判レビュー（最低1件）

### Phase 2: 評価用音声の準備（方針決定→入手）
- [x] 👀 ユーザー確認: **本人がマイクで読み上げ原稿を音読** に決定（実パスのマイク→whisperを再現・実声・正解=原稿）
- [x] 収音スクリプト `python/src/synchroni_note/bench/record_audio.py`（sounddevice, 16kHz mono WAV）を実装
- [x] 音声 `python/audio/sample01.wav`（70秒）＋ 正解 `python/audio/script01.txt` を配置
- [x] 🔬 機械検証: 音声長(70.0s)と正解テキストがスクリプトから読める（無音でないこと確認: peak0.10/RMS0.009）

### Phase 3: STT単体計測
- [x] tiny/base/medium × cpu_threads{4,8} × streaming/batch で RTF・CER を計測（threads=6は省略）＋チャンク長8/12スイープ
- [x] `doc/DD/DD-003/結果.md` にモデル/条件別の表を記録
- [x] 🔬 機械検証: 結果Markdownに全条件の数値が揃っている
- [x] 😈 DA批判レビュー（最低1件）

### Phase 4: STT/LLM同時実行スパイク＋ゲート判定
- [x] whisper(medium)併走下で qwen3:8b の tok/s を再測 → 孤立7.7 → 併走6.5（**-16%**）
- [x] スレッド総和が8コア超でのスラッシングを記録（whisper medium@10s/4thr: 孤立0.608 → Ollama併走1.484, **+144%**）
- [x] **合否ゲート判定**: 単体PASS（medium 8〜12秒で RTF 0.43〜0.61<1）/ 無対策の同時実行はFAIL（1.48） → **時間分離が必須**。3秒チャンク不可。
- [x] 考察を結果.mdに記録（基本設計 §5/§7/§9・ロードマップ §8 反映は本DDログ後に実施）
- [x] 🔬 機械検証: ゲート判定（条件付きPASS/無策FAIL）が結果Markdownに明記されている
- [x] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-07
- DD作成
- Phase 0 完了（精査・詳細化判定・DA調査をDD本文に記載）。
- Phase 1 完了: `faster-whisper` をランタイム依存に追加。`bench/stt_bench.py`（RTF/CER純関数＋faster-whisper呼び出し、streaming/batch両対応）と `tests/test_stt_bench.py`（11ケース）を実装。ruff緑・pytest 18 passed。
- Phase 2 完了: マイク録音方式に決定。`record_audio.py`（sounddevice）実装、本人音読70秒を `audio/sample01.wav` に録音、正解=`audio/script01.txt`。CER正規化に句読点除去を追加（pytest 19 passed）。
- Phase 3 完了: tiny/base/medium × threads{4,8} × batch/streaming ＋ チャンク長8/12スイープを計測。
  - batch RTF: tiny 0.02 / base 0.05 / medium 0.30。streaming(3s) RTF: medium 1.39〜1.78（>1）。
  - **3秒チャンクは30秒窓パディングでRTF爆発。8〜12秒VAD区切りで medium streaming RTF 0.43〜0.58 に回復**。
  - CER: medium 0.26 ≪ base 0.54 ≪ tiny 0.82（録音レベル低めで悲観側）。スレッド4→8の効果は小。
- Phase 4 完了: 同時実行スパイク。LLM孤立 7.7 → whisper(4thr)併走 6.5（-16%）。whisper medium@10s/4thr 孤立 0.608 → Ollama(既定~8thr)併走 1.484（+144%, スラッシング）。
  - **ゲート: 単体PASS / 無対策の同時実行FAIL → 時間分離が必須。3秒チャンク不可。日本語は medium 必須 → 二段STT（tiny/base即表示＋medium大窓/終了後再STT）が現実解。**
- 次: 知見を基本設計書 §5/§7/§9・ロードマップ §8 へ反映。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA批判レビュー

**DA観点:** （計測harnessが正しい値を測れているか／再現性）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | streaming計測が各チャンクを**独立に**文字起こしするため、faster-whisperの30秒窓・文脈を活かせずチャンク境界で文が切れ、CERが実パイプラインより悪化する。基本設計書§3.4の「VAD境界＋0.3〜0.5秒オーバーラップ」を模していない。 | 中 | `--modes streaming --chunk-seconds 3` と `--modes batch` のCERを比較するとstreamingが顕著に悪化するはず | 計測条件の代表性（streamingを過度に悲観） | streamingのCERは**上限（悲観値）**として扱うと結果.mdに明記。製品設計ではVAD境界＋オーバーラップで緩和。RTF（速度）の評価には影響小。 |
| 2 | CERの正規化が空白除去のみで、句読点・全角半角・カタカナ長音の表記揺れを吸収しない。faster-whisperの正規化と参照の作り方次第でCERが過大に出うる。 | 低 | 句読点だけ違う参照/仮説でCERが非0になる | 指標定義の厳密性 | まずは素のCERで相対比較（モデル間・条件間）に使う。絶対値が必要なら正規化強化を別途検討。 |

### Phase 3 DA批判レビュー

**DA観点:** （計測条件が実運用を代表しているか）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | 録音レベルが低く（peak0.10/RMS0.009）、CER絶対値が全モデルで悲観方向に歪む。medium batch 0.26 も近接マイク/AGCならさらに下がる可能性が高い。絶対品質の合否（議事録に足るか）は本値では判断不可。 | 中 | 同一原稿を適正レベルで録り直すと medium CER が低下するはず | 計測の代表性（音声品質） | CERは**モデル間・条件間の相対比較**に使用。絶対品質判断は近接マイク/実VADで再測（製品期 or 追加録音）。要約品質ルーブリック評価は別途。 |
| 2 | streaming計測が**固定時間切り**（無音を無視した機械分割）で、実VAD（無音境界）より文を断片化しCERを悲観方向に歪める。本DDのstreaming CERは上限値。 | 中 | batchとstreamingのCER差（medium 0.26 vs 0.38〜0.60）を比較 | 計測手法の理想化 | 結果.mdに「上限値」と明記。製品設計はVAD境界＋0.3〜0.5秒オーバーラップ（基本設計§3.4）で緩和。RTF評価には影響小。 |

### Phase 4 DA批判レビュー

**DA観点:** （ゲート判定の妥当性・同時実行条件の代表性）

| # | 発見した問題/改善点 | 重要度 | 再現手順（高/中は必須） | DA観点 | 対応 |
|---|-------------------|--------|----------------------|--------|------|
| 1 | 同時実行の劣化はスレッド割当に強依存し、本テストは Ollama `num_thread` 未制限（既定~8）の**最悪ケース**。基本設計の推奨設定（`num_thread`≤3 / `NUM_PARALLEL=1` / whisper=4 で総和≤8）での「分割すれば同時実行が成立するか」は未実測。「同時実行は必ず不可」と結論づけるのは早計。 | 中 | whisper4＋Ollama num_thread=3 に固定して再測すると劣化が縮むはず | ゲート条件の代表性（最悪ケースのみ） | 既定は**時間分離**に倒す（安全側）。厳格スレッド分割での同時実行可否は DD-005（liveパイプ縦切り）で実測して詰める。 |
| 2 | 評価エンジンは faster-whisper。製品 whisper.cpp(whisper-rs) は RTF が異なる（一般に遅い側）ため、本ゲート判定を製品の最終判断にそのまま使えない。 | 中 | 同条件を whisper.cpp で実行しRTFを比較 | エンジン差（評価期↔製品期） | 基本設計 §5 に「製品期で whisper.cpp 再測」を明記済み。DD-005以降で製品エンジンの実測を必須化。 |
| 3 | 単一録音・単一話者・70秒の小サンプルで、長時間会議や複数話者・雑音環境のRTF/CER変動を代表しない。 | 低 | 長尺・多話者音声で再測 | サンプル代表性 | Phase 0 の評価音声拡充（複数サンプル）を後続で検討。本DDは方向性確定が目的。 |
