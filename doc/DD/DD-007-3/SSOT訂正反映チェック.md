# SSOT訂正反映チェックリスト（DD-007-3 Phase 2 成果物）

> [基本設計書 §8 訂正一覧](../../spec/基本設計書.md#L218-L227) の各行が論理モデル（[ER図](ER図.md)）に反映されているかを検証する。未反映0が合格条件。

| # | SSOT §8 の項目 | 訂正/再フレーム内容 | 反映先テーブル/カラム | 反映 |
|---|---------------|--------------------|----------------------|:----:|
| 1 | File 1 共通仕様・SQLite・カレンダー | 概ね踏襲。`voice_profile` の役割再定義 | `participants.voice_hint`（名寄せヒント表示用） | ✅ |
| 2 | File 2 リアルタイムパイプライン | 「LLM整形＝真実源」撤回。確定即表示が主役／整形は別レイヤ | `timeline_elements.text_raw`(immutable, NOT NULL) と `text_refined`(NULL可) ＋ `is_refined` | ✅ |
| 3 | File 3 話者分離 | whisper組込diarization不可。外部スタック・会議中は仮ID＋人間確定 | `speaker_mappings`(confirmed/ai_guess 2層) ＋ `speaker_id INTEGER`(仮ID) ＋ `confirmed_participant_id` | ✅ |
| 4 | File 4 人間メモ | timestamp挿入を直列化。清書で最優先・全文保持 | `timeline_elements.kind='human_memo'`＋`t_ms`＋`seq`（全文 `text_raw` 保持・要約段で切らない方針はFile5バッチ側ロジック） | ✅ |
| 5 | File 5 議事録作成 | モデル名を実在タグへ。所要時間を実測表示。長文 map-reduce | `meetings.batch_model`（実在タグ値）＋`generation_seconds`（実測秒） | ✅ |

## 追加反映（§8表以外のSSOT記述）

| SSOT箇所 | 内容 | 反映先 | 反映 |
|---------|------|--------|:----:|
| [§3.1](../../spec/基本設計書.md#L83-L102) | `seq:u64` で順序保証／表示名は都度導出 | `timeline_elements.seq`＋UNIQUE／表示名はDB非保持 | ✅ |
| [§3.4](../../spec/基本設計書.md#L153) | WAL有効・別タスクバッチflush | DD-007-4 PRAGMA `journal_mode=WAL`／逐次flush設計 | ✅ |
| [§5](../../spec/基本設計書.md#L190) | 終了後オフライン diarization 用に音声保存 | `app_settings.keep_audio`＋`meetings.audio_path` | ✅ |
| [§6](../../spec/基本設計書.md#L196-L201) | 清書入力統合・出力を final_minutes に・status=completed | 1会議スコープ集約可（ER図§3）／`final_minutes`/`status` | ✅ |
| [§2.2 遷移](../../spec/基本設計書.md#L45-L54) | scheduled→active→generating→completed | `meetings.status` enum 拡張 | ✅ |

## 🔬 機械検証
SSOT §8 の全5行＋追加5項目が「反映先」を持つ（未反映0）。要件File1の旧4表案で欠けていた中核（timeline / speaker mapping）・設定・音声保存・実測メタを全て補完済み。
