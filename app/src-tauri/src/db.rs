//! SQLite データアクセス層（DD-012-3）。
//!
//! 設計判断（DD-012-3 Phase 0）: **DBの持ち主は Rust(Tauri) 単独**。Python サイドカーは
//! DBに触れず stdout(JSON Lines) のみ。よって書き込み主体は本モジュールに一本化され、
//! WAL の多プロセス同時オープン競合が構造的に起きない。
//!
//! スキーマは `doc/spec/db/schema.sql`（唯一の正）を `include_str!` でビルド時に埋め込む。
//! 実装側に複製DDLを持たない（schema.sql が唯一の正・データベース設計.md §5）。

use rusqlite::{params, Connection, OptionalExtension, Result, Row};
use serde::{Deserialize, Serialize};

/// schema.sql（唯一の正）をビルド時に埋め込む。パスは本ファイル(app/src-tauri/src/db.rs)起点。
const SCHEMA_SQL: &str = include_str!("../../../doc/spec/db/schema.sql");

/// 会議（集約ルート / `meetings`）。フィールド名はDBカラムと一致させ、そのまま frontend に渡す。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Meeting {
    pub id: String,
    pub title: String,
    pub agenda: Option<String>,
    pub place: Option<String>,
    pub scheduled_start: String,
    pub scheduled_end: Option<String>,
    pub actual_start: Option<String>,
    pub actual_end: Option<String>,
    pub status: String,
    pub final_minutes: Option<String>,
    pub batch_model: Option<String>,
    pub generation_seconds: Option<i64>,
    pub audio_path: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

impl Meeting {
    fn from_row(row: &Row) -> Result<Self> {
        Ok(Meeting {
            id: row.get("id")?,
            title: row.get("title")?,
            agenda: row.get("agenda")?,
            place: row.get("place")?,
            scheduled_start: row.get("scheduled_start")?,
            scheduled_end: row.get("scheduled_end")?,
            actual_start: row.get("actual_start")?,
            actual_end: row.get("actual_end")?,
            status: row.get("status")?,
            final_minutes: row.get("final_minutes")?,
            batch_model: row.get("batch_model")?,
            generation_seconds: row.get("generation_seconds")?,
            audio_path: row.get("audio_path")?,
            created_at: row.get("created_at")?,
            updated_at: row.get("updated_at")?,
        })
    }
}

/// 参加者（`participants`）。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Participant {
    pub id: String,
    pub meeting_id: String,
    pub name: String,
    pub role: Option<String>,
    pub voice_hint: Option<String>,
    pub sort_order: Option<i64>,
}

/// タイムライン要素（`timeline_elements`）。AI文字起こし or 人間メモ。`seq` が全順序キー。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TimelineElement {
    pub id: String,
    pub meeting_id: String,
    pub seq: i64,
    /// 'ai_transcription' | 'human_memo'
    pub kind: String,
    pub speaker_id: Option<i64>,
    pub t_ms: i64,
    pub text_raw: String,
    pub text_refined: Option<String>,
    pub is_refined: bool,
    pub created_at: String,
}

impl TimelineElement {
    fn from_row(row: &Row) -> Result<Self> {
        Ok(TimelineElement {
            id: row.get("id")?,
            meeting_id: row.get("meeting_id")?,
            seq: row.get("seq")?,
            kind: row.get("kind")?,
            speaker_id: row.get("speaker_id")?,
            t_ms: row.get("t_ms")?,
            text_raw: row.get("text_raw")?,
            text_refined: row.get("text_refined")?,
            is_refined: row.get("is_refined")?,
            created_at: row.get("created_at")?,
        })
    }
}

// ============ 接続 ============

/// ファイルDBを開き、スキーマ未適用なら適用して返す。接続ごとのPRAGMAも本関数で必ず通す。
pub fn open(path: &str) -> Result<Connection> {
    let conn = Connection::open(path)?;
    init(&conn)?;
    Ok(conn)
}

/// テスト用のインメモリDB（ファイルを汚さず CRUD を検証する）。
#[cfg(test)]
pub fn open_in_memory() -> Result<Connection> {
    let conn = Connection::open_in_memory()?;
    init(&conn)?;
    Ok(conn)
}

/// schema.sql を適用し、接続ごとに必須のPRAGMA（特に foreign_keys）を確実に有効化する。
///
/// schema.sql 内にも PRAGMA 行はあるが、`foreign_keys` はトランザクション内では無効化される等の
/// 罠があるため（DA#2）、適用後にもう一度明示で立てて空振りを防ぐ。
fn init(conn: &Connection) -> Result<()> {
    conn.execute_batch(SCHEMA_SQL)?;
    conn.pragma_update(None, "foreign_keys", true)?;
    Ok(())
}

// ============ meetings ============

/// 会議を1件挿入する。id・created_at・updated_at は呼び出し側が確定して渡す
/// （本層は時計/UUIDに依存しない純関数に保ち、テストを決定的にする）。
pub fn insert_meeting(conn: &Connection, m: &Meeting) -> Result<()> {
    conn.execute(
        "INSERT INTO meetings (
            id, title, agenda, place, scheduled_start, scheduled_end,
            actual_start, actual_end, status, final_minutes, batch_model,
            generation_seconds, audio_path, created_at, updated_at
        ) VALUES (
            ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15
        )",
        params![
            m.id, m.title, m.agenda, m.place, m.scheduled_start, m.scheduled_end,
            m.actual_start, m.actual_end, m.status, m.final_minutes, m.batch_model,
            m.generation_seconds, m.audio_path, m.created_at, m.updated_at,
        ],
    )?;
    Ok(())
}

/// 会議を1件取得（無ければ None）。
pub fn get_meeting(conn: &Connection, id: &str) -> Result<Option<Meeting>> {
    conn.query_row(
        "SELECT * FROM meetings WHERE id = ?1",
        params![id],
        Meeting::from_row,
    )
    .optional()
}

/// 指定年月（ローカルISO8601前提）の会議を scheduled_start 昇順で返す（S-01 カレンダー）。
pub fn list_meetings_by_month(conn: &Connection, year: i32, month: u32) -> Result<Vec<Meeting>> {
    let prefix = format!("{:04}-{:02}%", year, month); // 'YYYY-MM%' 前方一致
    let mut stmt = conn.prepare(
        "SELECT * FROM meetings
         WHERE scheduled_start LIKE ?1
         ORDER BY scheduled_start ASC",
    )?;
    let rows = stmt.query_map(params![prefix], Meeting::from_row)?;
    rows.collect()
}

/// 会議のステータスのみ更新（scheduled→active→generating→completed/aborted）。
pub fn update_meeting_status(
    conn: &Connection,
    id: &str,
    status: &str,
    updated_at: &str,
) -> Result<()> {
    conn.execute(
        "UPDATE meetings SET status = ?2, updated_at = ?3 WHERE id = ?1",
        params![id, status, updated_at],
    )?;
    Ok(())
}

/// 清書結果を保存し status='completed' に確定する（S-07 保存 / DD-012-2 と接続）。
pub fn save_final_minutes(
    conn: &Connection,
    id: &str,
    final_minutes: &str,
    batch_model: Option<&str>,
    generation_seconds: Option<i64>,
    updated_at: &str,
) -> Result<()> {
    conn.execute(
        "UPDATE meetings SET
            final_minutes = ?2,
            batch_model = ?3,
            generation_seconds = ?4,
            status = 'completed',
            updated_at = ?5
         WHERE id = ?1",
        params![id, final_minutes, batch_model, generation_seconds, updated_at],
    )?;
    Ok(())
}

/// 予定日時のみ更新する（S-01 ドラッグ移動 / DD-012-9）。`scheduled_end` は無ければ NULL。
/// 時刻維持・所要時間維持は呼び出し側（frontend）で確定して渡す（本層は時計に依存しない）。
pub fn update_meeting_schedule(
    conn: &Connection,
    id: &str,
    scheduled_start: &str,
    scheduled_end: Option<&str>,
    updated_at: &str,
) -> Result<()> {
    conn.execute(
        "UPDATE meetings SET scheduled_start = ?2, scheduled_end = ?3, updated_at = ?4
         WHERE id = ?1",
        params![id, scheduled_start, scheduled_end, updated_at],
    )?;
    Ok(())
}

/// 会議の編集可能項目（タイトル/アジェンダ/場所/予定日時）を更新する（S-02 編集モード / DD-012-9）。
/// `status`・`final_minutes`・実績時刻・`created_at` には触れない（編集UIの責務外）。
pub fn update_meeting(conn: &Connection, m: &Meeting) -> Result<()> {
    conn.execute(
        "UPDATE meetings SET
            title = ?2, agenda = ?3, place = ?4,
            scheduled_start = ?5, scheduled_end = ?6, updated_at = ?7
         WHERE id = ?1",
        params![
            m.id, m.title, m.agenda, m.place,
            m.scheduled_start, m.scheduled_end, m.updated_at,
        ],
    )?;
    Ok(())
}

/// 会議を1件削除する（S-01 削除 / DD-012-9）。`participants` / `timeline_elements` /
/// `attachments` / `vocabularies` は **ON DELETE CASCADE** で連動削除される。
/// 存在しないIDでもエラーにせず 0 行更新で正常終了する（冪等な削除）。
pub fn delete_meeting(conn: &Connection, id: &str) -> Result<()> {
    conn.execute("DELETE FROM meetings WHERE id = ?1", params![id])?;
    Ok(())
}

// ============ participants ============

/// 参加者を1件挿入（会議作成 S-02）。
pub fn insert_participant(conn: &Connection, p: &Participant) -> Result<()> {
    conn.execute(
        "INSERT INTO participants (id, meeting_id, name, role, voice_hint, sort_order)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![p.id, p.meeting_id, p.name, p.role, p.voice_hint, p.sort_order],
    )?;
    Ok(())
}

/// 会議の参加者を sort_order 昇順（NULLは末尾）で返す。
pub fn list_participants(conn: &Connection, meeting_id: &str) -> Result<Vec<Participant>> {
    let mut stmt = conn.prepare(
        "SELECT id, meeting_id, name, role, voice_hint, sort_order
         FROM participants WHERE meeting_id = ?1
         ORDER BY sort_order IS NULL, sort_order ASC",
    )?;
    let rows = stmt.query_map(params![meeting_id], |row| {
        Ok(Participant {
            id: row.get("id")?,
            meeting_id: row.get("meeting_id")?,
            name: row.get("name")?,
            role: row.get("role")?,
            voice_hint: row.get("voice_hint")?,
            sort_order: row.get("sort_order")?,
        })
    })?;
    rows.collect()
}

/// 会議の参加者を全削除する（S-02 編集での「全入替」前処理 / DD-012-9）。
pub fn delete_participants(conn: &Connection, meeting_id: &str) -> Result<()> {
    conn.execute(
        "DELETE FROM participants WHERE meeting_id = ?1",
        params![meeting_id],
    )?;
    Ok(())
}

// ============ timeline_elements ============

/// タイムライン要素を1件挿入（確定セグメント or 人間メモ）。
pub fn insert_timeline_element(conn: &Connection, e: &TimelineElement) -> Result<()> {
    conn.execute(
        "INSERT INTO timeline_elements (
            id, meeting_id, seq, kind, speaker_id, t_ms,
            text_raw, text_refined, is_refined, created_at
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
        params![
            e.id, e.meeting_id, e.seq, e.kind, e.speaker_id, e.t_ms,
            e.text_raw, e.text_refined, e.is_refined, e.created_at,
        ],
    )?;
    Ok(())
}

/// 会議のタイムラインを seq 昇順で返す（S-03 詳細・清書入力）。
pub fn list_timeline(conn: &Connection, meeting_id: &str) -> Result<Vec<TimelineElement>> {
    let mut stmt = conn.prepare(
        "SELECT * FROM timeline_elements WHERE meeting_id = ?1 ORDER BY seq ASC",
    )?;
    let rows = stmt.query_map(params![meeting_id], TimelineElement::from_row)?;
    rows.collect()
}

// ============ app_settings（単一行・DD-012-7） ============

/// アプリ設定（`app_settings` 単一行 id=1）。S-08 のフォームと1:1。
/// `use_llm_live`/`keep_audio` はDB上 INTEGER(0/1)、ここでは bool に正規化する。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AppSettings {
    pub mic_device: Option<String>,
    pub stt_model: Option<String>,
    pub live_model: Option<String>,
    pub batch_model: Option<String>,
    pub use_llm_live: bool,
    pub kv_cache_type: Option<String>,
    pub whisper_n_threads: Option<i64>,
    pub ollama_num_thread: Option<i64>,
    pub db_path: Option<String>,
    pub keep_audio: bool,
    pub updated_at: String,
}

/// 設定（id=1 単一行）を取得する。行は schema.sql の既定 INSERT で必ず存在する。
pub fn get_settings(conn: &Connection) -> Result<AppSettings> {
    conn.query_row(
        "SELECT mic_device, stt_model, live_model, batch_model, use_llm_live,
                kv_cache_type, whisper_n_threads, ollama_num_thread, db_path,
                keep_audio, updated_at
         FROM app_settings WHERE id = 1",
        [],
        |row| {
            Ok(AppSettings {
                mic_device: row.get("mic_device")?,
                stt_model: row.get("stt_model")?,
                live_model: row.get("live_model")?,
                batch_model: row.get("batch_model")?,
                use_llm_live: row.get::<_, i64>("use_llm_live")? != 0,
                kv_cache_type: row.get("kv_cache_type")?,
                whisper_n_threads: row.get("whisper_n_threads")?,
                ollama_num_thread: row.get("ollama_num_thread")?,
                db_path: row.get("db_path")?,
                keep_audio: row.get::<_, i64>("keep_audio")? != 0,
                updated_at: row.get("updated_at")?,
            })
        },
    )
}

/// 設定（id=1 単一行）を上書き保存する。`updated_at` は呼び出し側が確定して渡す。
pub fn save_settings(conn: &Connection, s: &AppSettings) -> Result<()> {
    conn.execute(
        "UPDATE app_settings SET
            mic_device = ?1, stt_model = ?2, live_model = ?3, batch_model = ?4,
            use_llm_live = ?5, kv_cache_type = ?6, whisper_n_threads = ?7,
            ollama_num_thread = ?8, db_path = ?9, keep_audio = ?10, updated_at = ?11
         WHERE id = 1",
        params![
            s.mic_device, s.stt_model, s.live_model, s.batch_model,
            s.use_llm_live as i64, s.kv_cache_type, s.whisper_n_threads,
            s.ollama_num_thread, s.db_path, s.keep_audio as i64, s.updated_at,
        ],
    )?;
    Ok(())
}

// ============ 確認用シードデータ（DD-012-3-1） ============

/// 確認用デモデータを投入する（DD-012-3-1）。**本番起動経路からは呼ばない**（開発・確認時のみ）。
///
/// 指定年月（=今日の年月を渡す想定）の**当月内**に、`completed`×3 / `active`×1 / `scheduled`×2
/// の会議を固定IDで生成する。当月内の固定日（≤24日＝全月で有効）に置くため月境界の日付計算が
/// 不要で、いつ開いても当月カレンダーに出る（DA#1 陳腐化対策）。完了会議1件には参加者・タイムライン・
/// 清書済み議事録も付与し、S-03 詳細の確認に使えるようにする。
///
/// 固定IDの存在チェックで**冪等**（二重投入しても増えない・DA#3）。FK順（meetings→participants
/// →timeline_elements）で投入する（DA#4）。
pub fn seed_demo_data(conn: &Connection, year: i32, month: u32) -> Result<()> {
    // 既に投入済みなら何もしない（冪等）。
    if get_meeting(conn, "seed-meeting-1")?.is_some() {
        return Ok(());
    }
    let ym = format!("{:04}-{:02}", year, month);

    // (id, 日, status, title, 清書済み議事録 or None)
    let specs: [(&str, u32, &str, &str, Option<&str>); 6] = [
        ("seed-meeting-1", 3, "completed", "キックオフ会議",
            Some("## 要約\n- プロジェクト方針を確認した。\n\n## 決定事項\n- 開発体制を確定。\n\n## TODO\n- 各自タスクを整理する。")),
        ("seed-meeting-2", 6, "completed", "設計レビュー",
            Some("## 要約\n- DB設計をレビューした。\n\n## 決定事項\n- schema.sql を唯一の正とする。\n\n## TODO\n- 実装に着手する。")),
        ("seed-meeting-3", 9, "completed", "進捗共有",
            Some("## 要約\n- 各機能の進捗を共有した。\n\n## 決定事項\n- リリース日候補を設定。\n\n## TODO\n- テスト計画を立てる。")),
        ("seed-meeting-4", 14, "active", "本日の定例", None),
        ("seed-meeting-5", 19, "scheduled", "リリース判定会議", None),
        ("seed-meeting-6", 24, "scheduled", "ふりかえり", None),
    ];
    for (id, day, status, title, minutes) in specs {
        let start = format!("{ym}-{day:02}T10:00:00");
        let done = status == "completed";
        let m = Meeting {
            id: id.into(),
            title: title.into(),
            agenda: Some(format!("{title} のアジェンダ")),
            place: Some("会議室A".into()),
            scheduled_start: start.clone(),
            scheduled_end: Some(format!("{ym}-{day:02}T11:00:00")),
            actual_start: if done || status == "active" { Some(start.clone()) } else { None },
            actual_end: if done { Some(format!("{ym}-{day:02}T11:00:00")) } else { None },
            status: status.into(),
            final_minutes: minutes.map(str::to_string),
            batch_model: minutes.map(|_| "gemma4:26b".to_string()),
            generation_seconds: minutes.map(|_| 42),
            audio_path: None,
            created_at: start.clone(),
            updated_at: start,
        };
        insert_meeting(conn, &m)?;
    }

    // 参加者は完了会議(seed-meeting-1)に付与（meetings の後＝FK順）。
    for (id, name, role, order) in [
        ("seed-part-1", "田中", "司会", 0_i64),
        ("seed-part-2", "鈴木", "開発", 1),
    ] {
        insert_participant(
            conn,
            &Participant {
                id: id.into(),
                meeting_id: "seed-meeting-1".into(),
                name: name.into(),
                role: Some(role.into()),
                voice_hint: None,
                sort_order: Some(order),
            },
        )?;
    }

    // タイムライン（AI文字起こし＋人間メモ）を seed-meeting-1 に付与。
    for (seq, kind, speaker, t_ms, text) in [
        (0_i64, "ai_transcription", Some(1_i64), 1000_i64, "本日はお集まりいただきありがとうございます。"),
        (1, "ai_transcription", Some(2), 5000, "資料の3ページ目から説明します。"),
        (2, "human_memo", None, 8000, "※要フォロー: 予算確認"),
        (3, "ai_transcription", Some(1), 12000, "では次回までに各自整理しましょう。"),
    ] {
        insert_timeline_element(
            conn,
            &TimelineElement {
                id: format!("seed-tl-{seq}"),
                meeting_id: "seed-meeting-1".into(),
                seq,
                kind: kind.into(),
                speaker_id: speaker,
                t_ms,
                text_raw: text.into(),
                text_refined: None,
                is_refined: false,
                created_at: format!("{ym}-03T10:00:00"),
            },
        )?;
    }
    Ok(())
}

// ============ tests ============

#[cfg(test)]
mod tests {
    use super::*;

    /// テスト用の最小 Meeting を生成（必要フィールドだけ与え、残りは None/既定）。
    fn meeting(id: &str, title: &str, scheduled_start: &str, status: &str) -> Meeting {
        Meeting {
            id: id.into(),
            title: title.into(),
            agenda: None,
            place: None,
            scheduled_start: scheduled_start.into(),
            scheduled_end: None,
            actual_start: None,
            actual_end: None,
            status: status.into(),
            final_minutes: None,
            batch_model: None,
            generation_seconds: None,
            audio_path: None,
            created_at: "2026-06-08T10:00:00".into(),
            updated_at: "2026-06-08T10:00:00".into(),
        }
    }

    #[test]
    fn schema_applies_and_seeds_settings() {
        // schema.sql が適用でき、app_settings の既定行(id=1)が投入されている。
        let conn = open_in_memory().unwrap();
        let cnt: i64 = conn
            .query_row("SELECT COUNT(*) FROM app_settings WHERE id = 1", [], |r| r.get(0))
            .unwrap();
        assert_eq!(cnt, 1);
    }

    #[test]
    fn meeting_roundtrip_keeps_japanese() {
        let conn = open_in_memory().unwrap();
        let m = meeting("m1", "定例ミーティング（６月）", "2026-06-08T10:00:00", "scheduled");
        insert_meeting(&conn, &m).unwrap();
        let got = get_meeting(&conn, "m1").unwrap().unwrap();
        assert_eq!(got, m); // 日本語タイトルを含め完全往復（DA#4 文字化け検証）
        assert!(get_meeting(&conn, "missing").unwrap().is_none());
    }

    #[test]
    fn list_by_month_filters_and_orders() {
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("b", "六月後半", "2026-06-20T09:00:00", "scheduled")).unwrap();
        insert_meeting(&conn, &meeting("a", "六月前半", "2026-06-03T09:00:00", "scheduled")).unwrap();
        insert_meeting(&conn, &meeting("c", "七月", "2026-07-01T09:00:00", "scheduled")).unwrap();
        let june = list_meetings_by_month(&conn, 2026, 6).unwrap();
        let ids: Vec<&str> = june.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(ids, vec!["a", "b"]); // 6月のみ・開始昇順
    }

    #[test]
    fn status_lifecycle_updates() {
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "scheduled")).unwrap();
        update_meeting_status(&conn, "m1", "active", "2026-06-08T10:05:00").unwrap();
        let got = get_meeting(&conn, "m1").unwrap().unwrap();
        assert_eq!(got.status, "active");
        assert_eq!(got.updated_at, "2026-06-08T10:05:00");
    }

    #[test]
    fn save_final_minutes_completes_meeting() {
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "active")).unwrap();
        save_final_minutes(&conn, "m1", "# 議事録\n- 決定事項", Some("gemma4:26b"), Some(42), "2026-06-08T11:00:00").unwrap();
        let got = get_meeting(&conn, "m1").unwrap().unwrap();
        assert_eq!(got.status, "completed");
        assert_eq!(got.final_minutes.as_deref(), Some("# 議事録\n- 決定事項"));
        assert_eq!(got.batch_model.as_deref(), Some("gemma4:26b"));
        assert_eq!(got.generation_seconds, Some(42));
    }

    #[test]
    fn timeline_returns_in_seq_order() {
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "active")).unwrap();
        for seq in [2_i64, 0, 1] {
            insert_timeline_element(
                &conn,
                &TimelineElement {
                    id: format!("e{seq}"),
                    meeting_id: "m1".into(),
                    seq,
                    kind: "ai_transcription".into(),
                    speaker_id: Some(seq),
                    t_ms: seq * 1000,
                    text_raw: format!("発話{seq}"),
                    text_refined: None,
                    is_refined: false,
                    created_at: "2026-06-08T10:00:00".into(),
                },
            )
            .unwrap();
        }
        let tl = list_timeline(&conn, "m1").unwrap();
        let seqs: Vec<i64> = tl.iter().map(|e| e.seq).collect();
        assert_eq!(seqs, vec![0, 1, 2]); // 挿入順に依らず seq 昇順
    }

    #[test]
    fn foreign_key_is_enforced() {
        // PRAGMA foreign_keys=ON が効いていれば、存在しない会議への子行挿入は失敗する（DA#2）。
        let conn = open_in_memory().unwrap();
        let orphan = TimelineElement {
            id: "e1".into(),
            meeting_id: "no-such-meeting".into(),
            seq: 0,
            kind: "ai_transcription".into(),
            speaker_id: None,
            t_ms: 0,
            text_raw: "孤児".into(),
            text_refined: None,
            is_refined: false,
            created_at: "2026-06-08T10:00:00".into(),
        };
        assert!(insert_timeline_element(&conn, &orphan).is_err());
    }

    fn status_counts(conn: &Connection, year: i32, month: u32) -> (usize, usize, usize) {
        let ms = list_meetings_by_month(conn, year, month).unwrap();
        let c = |s: &str| ms.iter().filter(|m| m.status == s).count();
        (c("completed"), c("active"), c("scheduled"))
    }

    #[test]
    fn seed_inserts_expected_distribution_in_target_month() {
        let conn = open_in_memory().unwrap();
        seed_demo_data(&conn, 2026, 6).unwrap();
        let ms = list_meetings_by_month(&conn, 2026, 6).unwrap();
        assert_eq!(ms.len(), 6);
        assert_eq!(status_counts(&conn, 2026, 6), (3, 1, 2)); // completed/active/scheduled
        assert!(ms.iter().all(|m| m.scheduled_start.starts_with("2026-06"))); // 全件当月
    }

    #[test]
    fn seed_is_idempotent() {
        let conn = open_in_memory().unwrap();
        seed_demo_data(&conn, 2026, 6).unwrap();
        seed_demo_data(&conn, 2026, 6).unwrap(); // 二重投入
        assert_eq!(list_meetings_by_month(&conn, 2026, 6).unwrap().len(), 6); // 増えない
    }

    #[test]
    fn seed_works_for_february_short_month() {
        // 固定日(≤24)が全月で有効＝2月でも破綻しないことを担保。
        let conn = open_in_memory().unwrap();
        seed_demo_data(&conn, 2026, 2).unwrap();
        let ms = list_meetings_by_month(&conn, 2026, 2).unwrap();
        assert_eq!(ms.len(), 6);
        assert!(ms.iter().all(|m| m.scheduled_start.starts_with("2026-02")));
    }

    #[test]
    fn seed_attaches_participants_and_timeline_and_minutes() {
        let conn = open_in_memory().unwrap();
        seed_demo_data(&conn, 2026, 6).unwrap();
        // 完了会議に参加者2名・タイムライン4件（seq昇順）・清書済み議事録。
        assert_eq!(list_participants(&conn, "seed-meeting-1").unwrap().len(), 2);
        let tl = list_timeline(&conn, "seed-meeting-1").unwrap();
        assert_eq!(tl.iter().map(|e| e.seq).collect::<Vec<_>>(), vec![0, 1, 2, 3]);
        assert!(tl.iter().any(|e| e.kind == "human_memo")); // メモも混在
        let m = get_meeting(&conn, "seed-meeting-1").unwrap().unwrap();
        assert!(m.final_minutes.is_some());
        assert_eq!(m.batch_model.as_deref(), Some("gemma4:26b"));
    }

    #[test]
    fn cascade_delete_removes_children() {
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "active")).unwrap();
        insert_participant(
            &conn,
            &Participant {
                id: "p1".into(),
                meeting_id: "m1".into(),
                name: "山田".into(),
                role: Some("司会".into()),
                voice_hint: None,
                sort_order: Some(0),
            },
        )
        .unwrap();
        conn.execute("DELETE FROM meetings WHERE id = ?1", params!["m1"]).unwrap();
        assert!(list_participants(&conn, "m1").unwrap().is_empty()); // ON DELETE CASCADE
    }

    #[test]
    fn settings_roundtrip_and_default() {
        let conn = open_in_memory().unwrap();
        // schema 既定行が読める（SSOT §3.4/§4.1 の初期値）。
        let def = get_settings(&conn).unwrap();
        assert_eq!(def.stt_model.as_deref(), Some("whisper base"));
        assert_eq!(def.live_model.as_deref(), Some("qwen3:8b"));
        assert_eq!(def.whisper_n_threads, Some(4));
        assert!(!def.use_llm_live); // 既定OFF（DD-012-4: 非力環境配慮）
        assert!(!def.keep_audio);
        // 変更を保存して完全往復（日本語含むデバイス名も）。
        let mut s = def.clone();
        s.stt_model = Some("whisper small".into());
        s.whisper_n_threads = Some(6);
        s.keep_audio = true;
        s.mic_device = Some("USB会議マイク".into());
        s.updated_at = "2026-06-08T12:00:00".into();
        save_settings(&conn, &s).unwrap();
        assert_eq!(get_settings(&conn).unwrap(), s);
    }

    #[test]
    fn delete_meeting_cascades_and_is_idempotent() {
        // DD-012-9: 削除で子（participants/timeline）も連動消去。存在しないIDは無害。
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "completed")).unwrap();
        insert_participant(
            &conn,
            &Participant {
                id: "p1".into(),
                meeting_id: "m1".into(),
                name: "山田".into(),
                role: None,
                voice_hint: None,
                sort_order: Some(0),
            },
        )
        .unwrap();
        insert_timeline_element(
            &conn,
            &TimelineElement {
                id: "e1".into(),
                meeting_id: "m1".into(),
                seq: 0,
                kind: "ai_transcription".into(),
                speaker_id: Some(1),
                t_ms: 0,
                text_raw: "あ".into(),
                text_refined: None,
                is_refined: false,
                created_at: "2026-06-08T10:00:00".into(),
            },
        )
        .unwrap();
        delete_meeting(&conn, "m1").unwrap();
        assert!(get_meeting(&conn, "m1").unwrap().is_none());
        assert!(list_participants(&conn, "m1").unwrap().is_empty()); // CASCADE
        assert!(list_timeline(&conn, "m1").unwrap().is_empty()); // CASCADE
        delete_meeting(&conn, "missing").unwrap(); // 存在しないIDでもOK（0行）
    }

    #[test]
    fn update_schedule_changes_datetime_only() {
        // DD-012-9: ドラッグ移動。start/end/updated_at のみ変わり status 等は不変。
        let conn = open_in_memory().unwrap();
        let mut m = meeting("m1", "会議", "2026-06-08T10:00:00", "scheduled");
        m.scheduled_end = Some("2026-06-08T11:00:00".into());
        insert_meeting(&conn, &m).unwrap();
        update_meeting_schedule(
            &conn,
            "m1",
            "2026-06-10T10:00:00",
            Some("2026-06-10T11:00:00"),
            "2026-06-08T12:00:00",
        )
        .unwrap();
        let got = get_meeting(&conn, "m1").unwrap().unwrap();
        assert_eq!(got.scheduled_start, "2026-06-10T10:00:00");
        assert_eq!(got.scheduled_end.as_deref(), Some("2026-06-10T11:00:00"));
        assert_eq!(got.updated_at, "2026-06-08T12:00:00");
        assert_eq!(got.status, "scheduled"); // 移動では status を触らない
        // 終日（end なし）へも更新できる。
        update_meeting_schedule(&conn, "m1", "2026-06-11T09:00:00", None, "2026-06-08T12:30:00").unwrap();
        assert!(get_meeting(&conn, "m1").unwrap().unwrap().scheduled_end.is_none());
    }

    #[test]
    fn update_meeting_edits_fields_but_not_status_or_minutes() {
        // DD-012-9: 編集は title/agenda/place/予定日時のみ。status・清書本文は保たれる。
        let conn = open_in_memory().unwrap();
        let mut m = meeting("m1", "旧タイトル", "2026-06-08T10:00:00", "completed");
        m.final_minutes = Some("## 議事録".into());
        m.batch_model = Some("gemma4:26b".into());
        insert_meeting(&conn, &m).unwrap();
        let edited = Meeting {
            title: "新タイトル".into(),
            agenda: Some("新アジェンダ".into()),
            place: Some("会議室B".into()),
            scheduled_start: "2026-06-09T14:00:00".into(),
            scheduled_end: Some("2026-06-09T15:00:00".into()),
            updated_at: "2026-06-08T12:00:00".into(),
            ..m.clone()
        };
        update_meeting(&conn, &edited).unwrap();
        let got = get_meeting(&conn, "m1").unwrap().unwrap();
        assert_eq!(got.title, "新タイトル");
        assert_eq!(got.agenda.as_deref(), Some("新アジェンダ"));
        assert_eq!(got.place.as_deref(), Some("会議室B"));
        assert_eq!(got.scheduled_start, "2026-06-09T14:00:00");
        assert_eq!(got.updated_at, "2026-06-08T12:00:00");
        assert_eq!(got.status, "completed"); // 編集の責務外は不変
        assert_eq!(got.final_minutes.as_deref(), Some("## 議事録"));
        assert_eq!(got.batch_model.as_deref(), Some("gemma4:26b"));
    }

    #[test]
    fn update_meeting_keeps_existing_participants() {
        // DD-012-9 Phase 4: 会議行だけ更新する経路（command の participants=None 相当）では
        // 参加者を消さない（完了会議の話者リンク保全の土台）。
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "旧", "2026-06-08T10:00:00", "completed")).unwrap();
        insert_participant(
            &conn,
            &Participant {
                id: "p1".into(),
                meeting_id: "m1".into(),
                name: "田中".into(),
                role: None,
                voice_hint: None,
                sort_order: Some(0),
            },
        )
        .unwrap();
        let mut edited = get_meeting(&conn, "m1").unwrap().unwrap();
        edited.title = "新".into();
        edited.updated_at = "2026-06-08T12:00:00".into();
        update_meeting(&conn, &edited).unwrap();
        assert_eq!(get_meeting(&conn, "m1").unwrap().unwrap().title, "新");
        assert_eq!(list_participants(&conn, "m1").unwrap().len(), 1); // 参加者は残る
    }

    #[test]
    fn delete_participants_clears_for_edit_replace() {
        // DD-012-9: 編集の「参加者を全入替」前処理。
        let conn = open_in_memory().unwrap();
        insert_meeting(&conn, &meeting("m1", "会議", "2026-06-08T10:00:00", "scheduled")).unwrap();
        for (id, name, order) in [("p1", "田中", 0_i64), ("p2", "鈴木", 1)] {
            insert_participant(
                &conn,
                &Participant {
                    id: id.into(),
                    meeting_id: "m1".into(),
                    name: name.into(),
                    role: None,
                    voice_hint: None,
                    sort_order: Some(order),
                },
            )
            .unwrap();
        }
        delete_participants(&conn, "m1").unwrap();
        assert!(list_participants(&conn, "m1").unwrap().is_empty());
    }
}
