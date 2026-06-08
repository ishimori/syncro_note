-- SynchroniNote SQLite スキーマ（schema_version = 1）【正式版・唯一の正】
-- 設計の正: doc/spec/db/データベース設計.md ／ カラム定義の正: doc/spec/db/データ辞書.md
-- 上位SSOT: doc/spec/基本設計書.md ／ 由来スナップショット: DD-007（doc/DD/DD-007-*）
-- 評価期(Python: sqlite3/sqlx)・製品期(Rust: rusqlite/sqlx) で共有するプレーンDDL。
-- ★このファイルがスキーマの唯一の正。実装側は本ファイルを参照/ビルド時コピーで消費し、複製を別管理しないこと。
-- 適用前提: 接続ごとに `PRAGMA foreign_keys=ON;` を実行すること（SQLiteは既定OFF）。

-- ============ 接続/DB 設定 ============
PRAGMA journal_mode = WAL;      -- ホットパスをI/Oで止めない（SSOT §3.4）
PRAGMA foreign_keys = ON;       -- FK制約を有効化（接続ごとに必須）
PRAGMA synchronous = NORMAL;    -- WAL前提の妥当な耐久性/性能バランス

-- ============ 1. meetings（集約ルート） ============
CREATE TABLE IF NOT EXISTS meetings (
    id                 TEXT    PRIMARY KEY,                 -- UUID
    title              TEXT    NOT NULL,
    agenda             TEXT,                                -- Markdown
    place              TEXT,                                -- 場所 / URL
    scheduled_start    TEXT    NOT NULL,                    -- ISO8601
    scheduled_end      TEXT,
    actual_start       TEXT,                                -- 録音開始（t_ms の基点）
    actual_end         TEXT,
    status             TEXT    NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN ('scheduled','active','generating','completed','aborted')),
    final_minutes      TEXT,                                -- 清書Markdown
    batch_model        TEXT,                                -- 清書に使用したモデル名
    generation_seconds INTEGER,                             -- 清書所要秒
    audio_path         TEXT,                                -- keep_audio 時の音声実体パス
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meetings_status_start
    ON meetings (status, scheduled_start);                 -- カレンダー一覧(S-01)

-- ============ 2. participants ============
CREATE TABLE IF NOT EXISTS participants (
    id          TEXT PRIMARY KEY,                           -- UUID
    meeting_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    role        TEXT,
    voice_hint  TEXT,                                       -- 旧voice_profile: 名寄せヒント表示用(識別不可)
    sort_order  INTEGER,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_participants_meeting ON participants (meeting_id);

-- ============ 3. vocabularies ============
CREATE TABLE IF NOT EXISTS vocabularies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  TEXT NOT NULL,
    word        TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
    UNIQUE (meeting_id, word)
);
CREATE INDEX IF NOT EXISTS idx_vocab_meeting ON vocabularies (meeting_id);

-- ============ 4. attachments ============
CREATE TABLE IF NOT EXISTS attachments (
    id             TEXT PRIMARY KEY,                        -- UUID
    meeting_id     TEXT NOT NULL,
    file_name      TEXT NOT NULL,
    local_path     TEXT NOT NULL,                           -- アプリ内コピー先
    file_type      TEXT NOT NULL CHECK (file_type IN ('xlsx','pdf')),
    extracted_text TEXT,                                    -- パース結果キャッシュ
    parse_status   TEXT NOT NULL DEFAULT 'pending'
                   CHECK (parse_status IN ('pending','done','error')),
    created_at     TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_attachments_meeting ON attachments (meeting_id);

-- ============ 5. timeline_elements（中核） ============
-- 確定原文(text_raw)は真実源・不可変。LLM整形(text_refined)は任意の別レイヤ。
-- 人間メモは kind='human_memo'・speaker_id=NULL。seq で順序保証。
CREATE TABLE IF NOT EXISTS timeline_elements (
    id            TEXT PRIMARY KEY,                         -- UUID
    meeting_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,                         -- 順序保証(ai/memo共通の全順序キー)。memoも挿入位置のseqを採番。読み出しは ORDER BY seq
    kind          TEXT NOT NULL CHECK (kind IN ('ai_transcription','human_memo')),
    speaker_id    INTEGER,                                  -- ai_transcription のみ
    t_ms          INTEGER NOT NULL,                         -- 会議開始からの相対ms
    text_raw      TEXT NOT NULL,                            -- 確定原文 / メモ本文（immutable）
    text_refined  TEXT,                                     -- LLM整形（任意・後追い）
    is_refined    INTEGER NOT NULL DEFAULT 0 CHECK (is_refined IN (0,1)),
    created_at    TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
    UNIQUE (meeting_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_timeline_meeting_seq
    ON timeline_elements (meeting_id, seq);                 -- 順次読み出し・清書入力

-- ============ 6. speaker_mappings（中核） ============
-- (meeting_id, speaker_id) ごとに確定/推測の2層。表示名はDBに焼き込まず都度導出。
-- 導出規則: confirmed_name ?? ai_guess_name ?? ('Speaker_' || speaker_id)
CREATE TABLE IF NOT EXISTS speaker_mappings (
    meeting_id               TEXT    NOT NULL,
    speaker_id               INTEGER NOT NULL,
    confirmed_name           TEXT,                          -- 人間確定（最優先）
    ai_guess_name            TEXT,                          -- AI推測
    confirmed_participant_id TEXT,                          -- 確定時の参加者紐付け
    updated_at               TEXT    NOT NULL,
    PRIMARY KEY (meeting_id, speaker_id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
    FOREIGN KEY (confirmed_participant_id) REFERENCES participants(id) ON DELETE SET NULL
);

-- ============ 7. app_settings（会議非従属・単一行） ============
CREATE TABLE IF NOT EXISTS app_settings (
    id                INTEGER PRIMARY KEY CHECK (id = 1),   -- 単一行強制
    mic_device        TEXT,
    stt_model         TEXT,
    live_model        TEXT,
    batch_model       TEXT,
    use_llm_live      INTEGER NOT NULL DEFAULT 0 CHECK (use_llm_live IN (0,1)),  -- 既定OFF: 非力環境配慮(DD-012-4)。会議中の追い上げ整形は任意
    kv_cache_type     TEXT CHECK (kv_cache_type IN ('f16','q8_0')),
    whisper_n_threads INTEGER,
    ollama_num_thread INTEGER,
    db_path           TEXT,
    keep_audio        INTEGER NOT NULL DEFAULT 0 CHECK (keep_audio IN (0,1)),
    updated_at        TEXT NOT NULL
);

-- 既定設定の初期投入（実在タグ／SSOT §3.4・§4.1 準拠の初期値）
INSERT OR IGNORE INTO app_settings
    (id, stt_model, live_model, batch_model, use_llm_live, kv_cache_type,
     whisper_n_threads, ollama_num_thread, keep_audio, updated_at)
VALUES
    (1, 'whisper base', 'qwen3:8b', 'gemma4:26b', 0, 'q8_0', 4, 4, 0, '1970-01-01T00:00:00');

-- 版管理・マイグレーションは行わない（過去データ移行不要の前提）。
-- スキーマ変更時は .sqlite を削除して本ファイルから再生成する。詳細: データベース設計.md §5 スキーマ適用方針
