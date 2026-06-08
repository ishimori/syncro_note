//! frontend(Vue) ↔ SQLite を結ぶ Tauri command 層（DD-012-3 Phase 2）。
//!
//! `db.rs`（純 rusqlite）はそのままに、ここで Tauri 依存（State/AppHandle）を引き受ける。
//! DBの持ち主は Rust 単独（Phase 0 設計判断）。接続は1本を `DbState` に持ち、各コマンドで lock する。
//!
//! 時刻/UUID は frontend が確定して渡す（`db.rs` の純関数設計に合わせる）。本層は受け取った
//! 行をそのまま読み書きするだけで、時計・乱数に依存しない。

use std::sync::Mutex;

use serde::Serialize;
use tauri::{App, AppHandle, Manager, State};

use crate::db::{self, AppSettings, Attachment, Meeting, Participant, TimelineElement};

/// アプリ唯一の DB 接続（書き込み主体は Rust 単独なので 1 接続を Mutex で共有）。
pub struct DbState(pub Mutex<rusqlite::Connection>);

/// S-03 詳細表示用に、会議・参加者・タイムラインをまとめて返す。
#[derive(Serialize)]
pub struct MeetingDetail {
    pub meeting: Meeting,
    pub participants: Vec<Participant>,
    pub timeline: Vec<TimelineElement>,
}

/// セットアップ時に DB を開いて `DbState` を manage する。
///
/// dev(debug) と本番(release)で **別ファイル**を使う（`*.dev.sqlite` / `*.sqlite`）。dev で投入する
/// 確認用シードが本番DBに混入しないようにするため（DD-012-3-1 DA#2 本番汚染対策）。シード自体は
/// frontend が dev のときだけ `seed_demo` を呼ぶ（当月の year/month を JS 側から渡す）。
pub fn init(app: &App) -> Result<(), Box<dyn std::error::Error>> {
    let dir = app.path().app_data_dir()?;
    std::fs::create_dir_all(&dir)?;
    let file = if cfg!(debug_assertions) {
        "synchroni_note.dev.sqlite"
    } else {
        "synchroni_note.sqlite"
    };
    let path = dir.join(file);
    let conn = db::open(path.to_str().ok_or("DBパスが非UTF-8")?)?;
    eprintln!("[db] opened {}", path.display());
    app.manage(DbState(Mutex::new(conn)));
    Ok(())
}

/// rusqlite のエラーを frontend へ返す String へ畳む小ヘルパ。
fn map_err<T>(r: rusqlite::Result<T>) -> Result<T, String> {
    r.map_err(|e| e.to_string())
}

/// 指定年月の会議を scheduled_start 昇順で返す（S-01 カレンダー）。
#[tauri::command]
pub fn list_meetings(
    state: State<'_, DbState>,
    year: i32,
    month: u32,
) -> Result<Vec<Meeting>, String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::list_meetings_by_month(&conn, year, month))
}

/// 会議＋参加者を保存する（S-02 作成）。id・各時刻は frontend が確定して渡す。
/// FK順（meetings→participants）で投入する。
#[tauri::command]
pub fn create_meeting(
    state: State<'_, DbState>,
    meeting: Meeting,
    participants: Vec<Participant>,
    timeline: Vec<TimelineElement>,
) -> Result<(), String> {
    let mut conn = state.0.lock().map_err(|e| e.to_string())?;
    // meeting→participants→timeline を1トランザクションで（途中失敗で半端な行を残さない）。
    let tx = conn.transaction().map_err(|e| e.to_string())?;
    map_err(db::insert_meeting(&tx, &meeting))?;
    for p in &participants {
        map_err(db::insert_participant(&tx, p))?;
    }
    for e in &timeline {
        map_err(db::insert_timeline_element(&tx, e))?;
    }
    tx.commit().map_err(|e| e.to_string())?;
    Ok(())
}

/// 会議を1件削除する（S-01 削除 / DD-012-9）。子（参加者・タイムライン・添付・用語）は CASCADE で連動削除。
#[tauri::command]
pub fn delete_meeting(state: State<'_, DbState>, id: String) -> Result<(), String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::delete_meeting(&conn, &id))
}

/// 予定日時のみ更新する（S-01 ドラッグ移動 / DD-012-9）。時刻維持・所要時間維持は frontend が確定して渡す。
#[tauri::command]
pub fn update_meeting_schedule(
    state: State<'_, DbState>,
    id: String,
    scheduled_start: String,
    scheduled_end: Option<String>,
    updated_at: String,
) -> Result<(), String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::update_meeting_schedule(
        &conn,
        &id,
        &scheduled_start,
        scheduled_end.as_deref(),
        &updated_at,
    ))
}

/// 会議の編集（S-02 編集モード / DD-012-9）。会議行を更新し、`participants` が `Some` のときだけ
/// 参加者を全入替する（`None`＝参加者に触れない＝完了会議で話者リンク
/// `timeline_elements.confirmed_participant_id` を保全する）。会議行＋参加者は **1トランザクション**で
/// 行う（`create_meeting` と同じく FK 順を守り、途中失敗で半端な行を残さない）。
#[tauri::command]
pub fn update_meeting(
    state: State<'_, DbState>,
    meeting: Meeting,
    participants: Option<Vec<Participant>>,
) -> Result<(), String> {
    let mut conn = state.0.lock().map_err(|e| e.to_string())?;
    let tx = conn.transaction().map_err(|e| e.to_string())?;
    map_err(db::update_meeting(&tx, &meeting))?;
    if let Some(ps) = &participants {
        map_err(db::delete_participants(&tx, &meeting.id))?;
        for p in ps {
            map_err(db::insert_participant(&tx, p))?;
        }
    }
    tx.commit().map_err(|e| e.to_string())?;
    Ok(())
}

/// 会議1件の詳細（本体＋参加者＋タイムライン）を返す（S-03 詳細）。無ければ null。
#[tauri::command]
pub fn get_meeting_detail(
    state: State<'_, DbState>,
    id: String,
) -> Result<Option<MeetingDetail>, String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    let Some(meeting) = map_err(db::get_meeting(&conn, &id))? else {
        return Ok(None);
    };
    let participants = map_err(db::list_participants(&conn, &id))?;
    let timeline = map_err(db::list_timeline(&conn, &id))?;
    Ok(Some(MeetingDetail {
        meeting,
        participants,
        timeline,
    }))
}

/// 確認用デモデータを投入する（**dev のみ frontend が呼ぶ**・冪等）。year/month は当月を JS から渡す。
#[tauri::command]
pub fn seed_demo(state: State<'_, DbState>, year: i32, month: u32) -> Result<(), String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::seed_demo_data(&conn, year, month))
}

/// 添付の保存先ディレクトリ（`app_data_dir/attachments/`）を作って返す。
fn attachments_dir(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("attachments");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

/// 事前資料を取り込む（S-02 / DD-012-10）。元ファイルをアプリ内へコピー→`pending` 行作成→
/// サイドカー抽出→`done`/`error`＋本文を反映し、確定後の行を返す。
///
/// 抽出（サイドカー実行）中は **DB ロックを保持しない**（数秒かかるため UI/他コマンドを止めない）。
/// id・file_type・created_at は frontend が確定して渡す（`db.rs` の純関数設計に合わせる）。
#[tauri::command]
pub fn add_attachment(
    app: AppHandle,
    state: State<'_, DbState>,
    id: String,
    meeting_id: String,
    src_path: String,
    file_name: String,
    file_type: String,
    created_at: String,
) -> Result<Attachment, String> {
    // 1) アプリ内へコピー（元ファイルが消えても抽出/再表示できるように local_path を持つ）。
    let dest = attachments_dir(&app)?.join(format!("{id}_{file_name}"));
    std::fs::copy(&src_path, &dest).map_err(|e| format!("ファイルのコピーに失敗: {e}"))?;
    let local_path = dest.to_string_lossy().to_string();

    // 2) pending 行を作る（ここだけロック→即解放）。
    let mut row = Attachment {
        id,
        meeting_id,
        file_name,
        local_path: local_path.clone(),
        file_type: file_type.clone(),
        extracted_text: None,
        parse_status: "pending".into(),
        created_at,
    };
    {
        let conn = state.0.lock().map_err(|e| e.to_string())?;
        map_err(db::insert_attachment(&conn, &row))?;
    }

    // 3) 抽出（ロック非保持。失敗してもファイル/行は残し error に倒す＝会議作成を妨げない）。
    let outcome = crate::extract_text_blocking(&local_path, Some(&file_type));
    let (status, text): (String, Option<String>) = match outcome {
        Ok(o) if o.status == "done" => ("done".into(), o.text),
        Ok(o) => {
            eprintln!("[attach] extract error: {:?}", o.message);
            ("error".into(), None)
        }
        Err(e) => {
            eprintln!("[attach] extract failed: {e}");
            ("error".into(), None)
        }
    };

    // 4) 結果を反映（再ロック）。
    {
        let conn = state.0.lock().map_err(|e| e.to_string())?;
        map_err(db::update_attachment_parse(
            &conn,
            &row.id,
            &status,
            text.as_deref(),
        ))?;
    }
    row.parse_status = status;
    row.extracted_text = text;
    Ok(row)
}

/// 会議の添付一覧を返す（S-02 一覧・S-03 添付チップ）。
#[tauri::command]
pub fn list_attachments(
    state: State<'_, DbState>,
    meeting_id: String,
) -> Result<Vec<Attachment>, String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::list_attachments(&conn, &meeting_id))
}

/// 添付を1件削除する（行＋コピー済みファイル）。ファイル削除は best-effort（失敗しても行は消す）。
#[tauri::command]
pub fn remove_attachment(state: State<'_, DbState>, id: String) -> Result<(), String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    // 先に local_path を引いてから行削除（ファイルの後始末用）。
    let local_path = db::get_attachment_path(&conn, &id).map_err(|e| e.to_string())?;
    map_err(db::delete_attachment(&conn, &id))?;
    if let Some(p) = local_path {
        let _ = std::fs::remove_file(p); // best-effort（既に無くてもOK）
    }
    Ok(())
}

/// 設定（app_settings 単一行）を返す（S-08 ロード／DD-012-7）。
#[tauri::command]
pub fn get_settings(state: State<'_, DbState>) -> Result<AppSettings, String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::get_settings(&conn))
}

/// 設定を保存する（S-08 保存／DD-012-7）。`updated_at` は frontend が確定して渡す。
#[tauri::command]
pub fn save_settings(state: State<'_, DbState>, settings: AppSettings) -> Result<(), String> {
    let conn = state.0.lock().map_err(|e| e.to_string())?;
    map_err(db::save_settings(&conn, &settings))
}
