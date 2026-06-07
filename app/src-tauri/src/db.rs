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
}
