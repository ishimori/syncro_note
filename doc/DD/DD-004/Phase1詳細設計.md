# DD-004 Phase 1 実装前詳細化（👀 レビュー対象）

> A方式（faster-whisper の word timestamps で参照RTTMを自前生成）の詳細設計。**この内容に合意後にコーディング開始**。
> 既存作法に合わせ、ハーネスは `src/synchroni_note/` 配下のモジュールとし `uv run python -m ...` で回す（`python/scripts/` は存在しないため不採用。DD-003/005 と同じ）。

## 1. モジュール構成（触る/新規ファイル）

| パス | 種別 | 責務 |
|------|------|------|
| `python/audio/script02_turns.json` | 新規(データ) | sample02 の**話者ラベル付きターン**正解（10ターン, 鈴木↔佐藤交互）。台本.md から起こした構造化データ。RTTM導出の入力 |
| `python/audio/sample02.rttm` | 生成物 | 自動生成される参照RTTM（コミットして再現性確保） |
| `src/synchroni_note/diarization/__init__.py` | 新規 | パッケージ |
| `src/synchroni_note/diarization/reference.py` | 新規 | **forced alignment で参照RTTM生成**（純関数中心・pytest対象） |
| `src/synchroni_note/diarization/rttm.py` | 新規 | RTTM 入出力。DER は `pyannote.metrics` を利用（下記§4） |
| `src/synchroni_note/diarization/base.py` | 新規 | 手法共通 I/F `diarize(audio, sr) -> list[Turn]`／`dummy` 実装（疎通用） |
| `src/synchroni_note/bench/diarization_bench.py` | 新規 | CLI: `--audio --ref --method` で DER/話者数/RTF を表出力（DD-003 bench に倣う） |
| `tests/test_diarization_reference.py` | 新規 | アライン純関数のユニットテスト |

> 既存 [`bench/vad_segment.py`](../../../python/src/synchroni_note/bench/vad_segment.py) の VAD と [`pipeline/transcribe.py`](../../../python/src/synchroni_note/pipeline/transcribe.py) の WhisperModel 作法（CPU/int8, ja, beam_size=1）を流用する。

## 2. 参照RTTM 自動生成アルゴリズム（reference.py の中核）

入力: `sample02.wav`（16k/mono/120s） + `script02_turns.json`（順序付き `[{speaker, text}]`）。

1. faster-whisper を `word_timestamps=True`（`vad_filter=True`）で実行 → 全単語列 `[(word, start_s, end_s)]` を得る。
2. 正規化（句読点・空白・記号除去）した **whisper連結文字列** と **正解ターン連結文字列** を `difflib.SequenceMatcher` で文字対応付け。
3. 正解側の「ターン境界の文字位置」を whisper 側の文字位置へ写像 → その位置を含む単語の時刻からターン境界時刻を決定。**境界は話者交代の無音ギャップに落ちる**ので、ギャップ中点を採用。
4. 各ターンに `[onset, offset, speaker]` を付与し RTTM 形式（`SPEAKER sample02 1 <onset> <dur> <NA> <NA> <spk> <NA> <NA>`）で出力。

交互・順序確定・**オーバーラップ無し**だから、この単調アラインで一意に決まる。

## 3. 手法共通インターフェース（base.py）

```python
@dataclass
class Turn:
    onset_s: float
    offset_s: float
    speaker: str   # 推定ラベル（"spk0" 等。正解の鈴木/佐藤とはDERが最適対応付け）

def diarize(audio: np.ndarray, sr: int) -> list[Turn]: ...
```

Phase 1 では `dummy`（全区間1話者 or VAD区間を交互ラベル）のみ実装してハーネス疎通を確認。実手法（pyannote / sherpa-onnx / 簡易クラスタリング）は **Phase 2** で同 I/F のアダプタとして追加。

## 4. DER 計測（rttm.py）— 自前実装（依存追加なし）

当初 `pyannote.metrics` を検討したが、**完全オフライン要件と依存最小**を優先し numpy だけで自前実装した（実装時の判断）。frameベース(10ms)で miss/false_alarm/confusion を数え、`collar=0.25`（標準250ms, 参照境界の前後を採点除外）で境界誤差を吸収。**話者ラベルの最適対応付けは総当たり**（話者数≤4想定）で confusion を最小化。正しさは `tests/test_diarization.py` で手計算値と一致を検証（完全一致=0 / 単一話者=0.5 / miss+FA ケース等）。

## 5. CLI（diarization_bench.py）出力イメージ

```
$ uv run python -m synchroni_note.bench.diarization_bench --audio audio/sample02.wav --ref audio/sample02.rttm --method dummy
method   DER     spk_ref spk_hyp RTF
dummy    0.83    2       1       0.01
```

## 6. エッジケース・エラー方針

- whisper がターンを跨いで1単語化／脱落 → §2 の文字対応で吸収（単語単位でなく文字単位写像）。
- 先頭/末尾の無音・カウントダウン残り → VAD と collar で吸収。1ターン目 onset は最初の有声単語に丸める。
- 正解ターン数と whisper セグメント数は**一致を要求しない**（文字対応ベースのため）。

## 7. テスト観点（pytest, Phase 1）

- 合成単語列（既知の時刻）＋既知ターンで、期待どおりの境界時刻・話者列が出るか（reference.py）。
- RTTM 書き出し→読み戻しのラウンドトリップ一致（rttm.py）。
- DER が既知の入力で手計算値と一致（collar=0 の単純ケース）。

## 8. Phase 1 完了条件（DoD）

- `sample02.rttm` が自動生成され、目視で話者交代位置が妥当（台本10ターンと整合）。
- `diarization_bench --method dummy` が DER 数値を出力（ハーネス疎通）。
- `uv run ruff check` 通過 ＋ 上記 pytest が緑。
