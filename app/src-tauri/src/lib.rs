// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};

// SQLite データアクセス層（DD-012-3）。純 rusqlite。
#[allow(dead_code)]
mod db;
// frontend ↔ DB を結ぶ Tauri command 層（DD-012-3 Phase 2）。
mod db_commands;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000; // uv のコンソール窓が一瞬出るのを抑止

/// 起動中の Python サイドカー1本を保持する（同時に1セッション）。
/// `stdin` はマイク制御（pause/resume/stop）の書き込み口。ウィンドウ破棄時の kill 用（DA#4/新4）。
struct SttSession {
    child: Child,
    stdin: Option<ChildStdin>,
}
struct SttState(Mutex<Option<SttSession>>);

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// `<repo>/python` を絶対パスで解決する（dev時）。
/// CARGO_MANIFEST_DIR = app/src-tauri なので、その2つ上 + python。
fn repo_python_dir() -> Result<PathBuf, String> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dir = manifest
        .parent() // app/
        .and_then(|p| p.parent()) // <repo>/
        .map(|p| p.join("python"))
        .ok_or_else(|| "python ディレクトリの親解決に失敗".to_string())?;
    dir.canonicalize()
        .map_err(|e| format!("python ディレクトリが見つかりません({}): {e}", dir.display()))
}

/// 添付の本文抽出結果（sidecar `--extract` の done/error を畳んだ形・DD-012-10）。
pub(crate) struct ExtractOutcome {
    pub status: String,       // "done" | "error"
    pub text: Option<String>, // done のとき抽出本文（空＝画像PDF等）
    pub message: Option<String>, // error のとき理由
}

/// サイドカー `--extract` を**同期(ブロッキング)実行**し、1行の JSON 結果を返す（DD-012-10）。
///
/// 文字起こし/清書の streaming relay（`spawn_and_relay`）と違い、結果を1個だけ受け取りたい
/// 抽出用途なので `output()` で待ち合わせる。uv の警告が混ざっても `type=extract` 行だけを拾う。
pub(crate) fn extract_text_blocking(
    path: &str,
    file_type: Option<&str>,
) -> Result<ExtractOutcome, String> {
    let py_dir = repo_python_dir()?;
    let mut cmd = Command::new("uv");
    cmd.current_dir(&py_dir)
        .env("PYTHONUTF8", "1") // 文字化け保険
        .args([
            "run",
            "python",
            "-m",
            "synchroni_note.pipeline.sidecar",
            "--extract",
            path,
        ]);
    if let Some(t) = file_type {
        cmd.args(["--type", t]);
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let output = cmd
        .output()
        .map_err(|e| format!("抽出サイドカー起動失敗(uv は PATH にある?): {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    // 末尾から type=extract の行を探す（最後の1行が結果。前段に警告が出ても無視）。
    for line in stdout.lines().rev() {
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if v.get("type").and_then(|t| t.as_str()) == Some("extract") {
            return Ok(ExtractOutcome {
                status: v
                    .get("status")
                    .and_then(|s| s.as_str())
                    .unwrap_or("error")
                    .to_string(),
                text: v.get("text").and_then(|t| t.as_str()).map(str::to_string),
                message: v.get("message").and_then(|m| m.as_str()).map(str::to_string),
            });
        }
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!("抽出結果(JSON)を取得できません: {}", stderr.trim()))
}

/// サイドカーが流す JSON Lines を、どの Tauri イベント名へ中継するかの系統。
/// STT（文字起こし）と Summary（清書・DD-012-2）で名前空間を分ける。
#[derive(Clone, Copy)]
enum Relay {
    Stt,
    Summary,
}

/// 1行=1JSON の `type` を、系統ごとの Tauri イベント名へ対応づける（未知は None で捨てる）。
fn relay_event(relay: Relay, ty: Option<&str>) -> Option<&'static str> {
    match relay {
        Relay::Stt => match ty {
            Some("meta") => Some("stt-meta"),
            Some("segment") => Some("stt-segment"),
            Some("speakers") => Some("stt-speakers"), // DD-012-5 会議後一括の話者ラベル(seq→spk)
            Some("done") => Some("stt-done"),
            Some("error") => Some("stt-error"),
            Some("level") => Some("stt-level"), // S-04 入力レベル（DD-012-8）
            Some("refined") => Some("stt-refined"), // DD-012-4 追い上げ整形
            Some("bypass") => Some("stt-bypass"), // DD-012-4 整形バイパス
            _ => None,
        },
        Relay::Summary => match ty {
            Some("summary-meta") => Some("summary-meta"),
            Some("summary-status") => Some("summary-status"),
            Some("summary-progress") => Some("summary-progress"),
            Some("summary-done") => Some("summary-done"),
            Some("error") => Some("summary-error"), // 清書の異常（stt-error とは別名）
            _ => None,
        },
    }
}

/// 子プロセスの stdin の扱い。
enum StdinMode {
    /// stdin 不要（ファイル文字起こし）。
    None,
    /// 開いたまま保持し、pause/resume/stop を書き込む（マイク・レベル計測）。
    Control,
    /// 起動直後に一括投入して即クローズ（EOF 通知）。清書の確定テキスト入力（DD-012-2）。
    Feed(String),
}

/// サイドカー(uv → python -m …)を起動し、stdout(JSON Lines)を Tauri イベントへ中継する。
///
/// 既存セッションがあれば先に kill（起動しっぱなし防止）。`stdin_mode` で stdin の扱いを切替える
/// （保持して制御 / 一括投入して EOF / 不要）。`relay` で emit するイベント名の系統（stt-* /
/// summary-*）を選ぶ。reader スレッドで即時 return。
fn spawn_and_relay(
    app: &AppHandle,
    state: &SttState,
    args: &[&str],
    relay: Relay,
    stdin_mode: StdinMode,
) -> Result<(), String> {
    // 進行中セッションがあれば先に終了（start→start での取り残し防止）。
    let prev = state.0.lock().unwrap().take();
    if let Some(sess) = prev {
        kill_session(sess);
    }

    let py_dir = repo_python_dir()?;
    let mut cmd = Command::new("uv");
    cmd.current_dir(&py_dir)
        .env("PYTHONUTF8", "1") // 文字化け保険（DA#2）
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if !matches!(stdin_mode, StdinMode::None) {
        cmd.stdin(Stdio::piped());
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("サイドカー起動失敗(uv は PATH にある?): {e}"))?;

    let out = BufReader::new(child.stdout.take().ok_or("stdout を取得できません")?);
    let err = BufReader::new(child.stderr.take().ok_or("stderr を取得できません")?);
    let child_stdin = child.stdin.take(); // piped 指定時のみ Some

    // stdin: 制御用に保持 or 確定テキストを一括投入して即クローズ（EOF＝python の read() が返る）。
    let keep_stdin = match stdin_mode {
        StdinMode::Feed(input) => {
            if let Some(mut si) = child_stdin {
                si.write_all(input.as_bytes())
                    .and_then(|_| si.flush())
                    .map_err(|e| format!("清書入力の送信に失敗: {e}"))?;
                // si はここで drop され EOF 通知。python は stdin を全読みしてから処理を始める。
            }
            None
        }
        StdinMode::Control => child_stdin, // マイク/レベル: 制御のため保持
        StdinMode::None => None,
    };
    let app2 = app.clone();

    // stderr は別スレッドでログへ（JSON に混ぜない＝DA-新3）
    std::thread::spawn(move || {
        for line in err.lines().map_while(Result::ok) {
            eprintln!("[sidecar] {line}");
        }
    });

    // stdout を1行ずつ → type を見て emit（reader スレッド・即時 return）
    std::thread::spawn(move || {
        for line in out.lines().map_while(Result::ok) {
            match serde_json::from_str::<Value>(&line) {
                Ok(v) => {
                    if let Some(ev) = relay_event(relay, v["type"].as_str()) {
                        eprintln!("[relay] emit {ev}"); // 検証用ログ
                        let _ = app2.emit(ev, v);
                    }
                }
                Err(_) => eprintln!("[relay] non-json: {line}"), // 捨てずログ（DA-新3）
            }
        }
        eprintln!("[relay] stdout closed (sidecar finished)");
    });

    *state.0.lock().unwrap() = Some(SttSession {
        child,
        stdin: keep_stdin,
    });
    Ok(())
}

/// `app_settings` から STT 用の (モデルサイズ, スレッド数) を読む（DD-012-7）。
/// 読めない/未設定なら (base, 4) に fallback して起動を止めない。
/// S-08 は "whisper base" 形式で持つため、先頭 "whisper " を除いて faster-whisper のサイズにする。
fn stt_settings(app: &AppHandle) -> (String, i64) {
    let fallback = ("base".to_string(), 4_i64);
    let state = app.state::<db_commands::DbState>();
    let Ok(conn) = state.0.lock() else {
        return fallback;
    };
    match db::get_settings(&conn) {
        Ok(s) => {
            let model = s
                .stt_model
                .as_deref()
                .map(|m| m.strip_prefix("whisper ").unwrap_or(m).trim().to_string())
                .filter(|m| !m.is_empty())
                .unwrap_or_else(|| "base".to_string());
            let threads = s.whisper_n_threads.filter(|&t| t > 0).unwrap_or(4);
            (model, threads)
        }
        Err(_) => fallback,
    }
}

/// サンプル音声ファイルを文字起こし（DD-011 3-C）。STTモデル/スレッドは S-08 設定に従う（DD-012-7）。
#[tauri::command]
fn start_transcription(
    app: AppHandle,
    state: State<'_, SttState>,
    audio_path: String,
    model: Option<String>,
) -> Result<(), String> {
    let (cfg_model, cfg_threads) = stt_settings(&app);
    let model = model.unwrap_or(cfg_model); // 明示指定があれば優先、無ければ設定値
    let threads = cfg_threads.to_string();
    eprintln!("[stt] file model={model} threads={threads}");
    let args = vec![
        "run",
        "python",
        "-m",
        "synchroni_note.pipeline.sidecar",
        audio_path.as_str(),
        "--model",
        model.as_str(),
        "--threads",
        threads.as_str(),
    ];
    spawn_and_relay(&app, state.inner(), &args, Relay::Stt, StdinMode::None)
}

/// ライブ追い上げ整形（DD-012-4）の設定: use_llm_live が ON なら Some(live_model)、OFF なら None。
fn live_refine_model(app: &AppHandle, on_override: Option<bool>) -> Option<String> {
    let state = app.state::<db_commands::DbState>();
    let conn = state.0.lock().ok()?;
    let s = db::get_settings(&conn).ok()?;
    // 今回ぶんの上書き（S-05 トグル）があれば優先、無ければ設定値 use_llm_live。
    if !on_override.unwrap_or(s.use_llm_live) {
        return None; // OFF＝整形ワーカーを起動せず qwen を一切ロードしない（追加コスト0）
    }
    // live ドロップダウンで「（無効）」/空 を選んだ場合も整形OFF扱い（無効モデルで空振りさせない）。
    let model = s.live_model.unwrap_or_default();
    let m = model.trim().to_string();
    if m.is_empty() || m == "（無効）" || m == "無効" || m.eq_ignore_ascii_case("none") {
        return None;
    }
    Some(m)
}

/// マイクからライブ文字起こし（DD-012-1）。`simulate` 指定時はファイルを mic 代替で流す（dev/テスト）。
/// stdin をパイプして pause/resume/stop を受け付ける。`use_llm_live` 時は追い上げ整形も起動（DD-012-4）。
#[tauri::command]
fn start_mic(
    app: AppHandle,
    state: State<'_, SttState>,
    model: Option<String>,
    simulate: Option<String>,
    refine: Option<bool>,
) -> Result<(), String> {
    let (cfg_model, cfg_threads) = stt_settings(&app);
    let model = model.unwrap_or(cfg_model); // S-08 設定の STT モデル（DD-012-7）
    let threads = cfg_threads.to_string();
    let refine_model = live_refine_model(&app, refine); // DD-012-4: 今回ぶん上書き or 設定値
    eprintln!(
        "[stt] mic model={model} threads={threads} simulate={} refine={}",
        simulate.is_some(),
        refine_model.is_some()
    );
    let mut args: Vec<&str> = vec!["run", "python", "-m", "synchroni_note.pipeline.sidecar"];
    match simulate.as_deref() {
        Some(path) => {
            args.push("--simulate");
            args.push(path);
        }
        None => args.push("--mic"),
    }
    args.push("--model");
    args.push(model.as_str());
    args.push("--threads");
    args.push(threads.as_str());
    if let Some(live) = refine_model.as_deref() {
        args.push("--refine");
        args.push("--live-model");
        args.push(live);
    }
    spawn_and_relay(&app, state.inner(), &args, Relay::Stt, StdinMode::Control)
}

/// マイクセッションの stdin に制御コマンド（pause/resume/stop）を1行書く。
fn write_ctrl(state: &SttState, cmd: &str) -> Result<(), String> {
    let mut guard = state.0.lock().unwrap();
    let sess = guard.as_mut().ok_or("録音セッションがありません")?;
    let stdin = sess.stdin.as_mut().ok_or("このセッションは制御できません")?;
    eprintln!("[stt] ctrl {cmd}"); // 検証用ログ（pause/resume/stop）
    stdin
        .write_all(format!("{cmd}\n").as_bytes())
        .and_then(|_| stdin.flush())
        .map_err(|e| format!("制御コマンド送信失敗({cmd}): {e}"))
}

#[tauri::command]
fn pause_mic(state: State<'_, SttState>) -> Result<(), String> {
    write_ctrl(state.inner(), "pause")
}

#[tauri::command]
fn resume_mic(state: State<'_, SttState>) -> Result<(), String> {
    write_ctrl(state.inner(), "resume")
}

#[tauri::command]
fn stop_mic(state: State<'_, SttState>) -> Result<(), String> {
    write_ctrl(state.inner(), "stop")
}

/// マイク入力レベル(RMS)のみを流す軽量サイドカー（S-04 プリフライト・DD-012-8）。
/// whisper は載せない。`simulate` 指定時はファイル給電（dev/テスト）。停止は `stop_mic`（stdin stop）。
#[tauri::command]
fn start_level(
    app: AppHandle,
    state: State<'_, SttState>,
    simulate: Option<String>,
) -> Result<(), String> {
    let mut args: Vec<&str> =
        vec!["run", "python", "-m", "synchroni_note.pipeline.sidecar", "--level"];
    if let Some(path) = simulate.as_deref() {
        args.push("--simulate");
        args.push(path);
    }
    spawn_and_relay(&app, state.inner(), &args, Relay::Stt, StdinMode::Control)
}

/// 清書(batch)/退避(live)モデル名を設定から読む（DD-012-7）。未設定なら既定へ fallback。
fn summarize_models(app: &AppHandle) -> (String, String) {
    let fallback = ("gemma4:26b".to_string(), "qwen3:8b".to_string());
    let state = app.state::<db_commands::DbState>();
    let Ok(conn) = state.0.lock() else {
        return fallback;
    };
    match db::get_settings(&conn) {
        Ok(s) => (
            s.batch_model.filter(|m| !m.is_empty()).unwrap_or(fallback.0),
            s.live_model.filter(|m| !m.is_empty()).unwrap_or(fallback.1),
        ),
        Err(_) => fallback,
    }
}

/// 清書の前提資料（DD-012-10）を一時ファイルに書き、そのパスを返す。
///
/// 当該会議の `done` 添付の `extracted_text`（空でないもの）を「## ファイル名 + 本文」で連結し、
/// `app_data_dir/summarize_materials.txt` に書く。done 資料が無ければ None（=資料なしで清書）。
fn write_materials_file(app: &AppHandle, meeting_id: &str) -> Option<String> {
    let attachments = {
        let state = app.state::<db_commands::DbState>();
        let conn = state.0.lock().ok()?;
        db::list_attachments(&conn, meeting_id).ok()?
    };
    let mut buf = String::new();
    for a in attachments {
        if a.parse_status == "done" {
            if let Some(t) = a.extracted_text.as_deref() {
                if !t.trim().is_empty() {
                    buf.push_str(&format!("## {}\n{}\n\n", a.file_name, t));
                }
            }
        }
    }
    if buf.trim().is_empty() {
        return None;
    }
    let dir = app.path().app_data_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    let path = dir.join("summarize_materials.txt");
    std::fs::write(&path, buf).ok()?;
    Some(path.to_string_lossy().to_string())
}

/// 会議終了→清書（DD-012-2）。確定テキスト(＋人間メモ)を stdin で渡し、gemma で議事録Markdownに
/// 清書して進捗を summary-* イベントで中継する。モデルは S-08 設定に従う（DD-012-7）。
///
/// `meeting_id` があれば、その会議の事前資料（done 添付の抽出本文）を前提資料として清書に統合する
/// （DD-012-10）。※ ライブ会議が予定(S-02)と紐づく経路は別途配線が必要（下記 DD のログ参照）。
#[tauri::command]
fn start_summarize(
    app: AppHandle,
    state: State<'_, SttState>,
    transcript: String,
    title: Option<String>,
    meeting_id: Option<String>,
) -> Result<(), String> {
    let (batch_model, live_model) = summarize_models(&app);
    let title = title.unwrap_or_default();
    // 事前資料（DD-012-10）: meeting_id があれば done 添付の本文を一時ファイルに集約して渡す。
    let materials_path = meeting_id
        .as_deref()
        .and_then(|id| write_materials_file(&app, id));
    eprintln!(
        "[summary] start batch={batch_model} live={live_model} chars={} materials={}",
        transcript.len(),
        materials_path.is_some()
    );
    let mut args: Vec<&str> = vec![
        "run",
        "python",
        "-m",
        "synchroni_note.pipeline.summarize_sidecar",
        "-", // 確定テキストは stdin から受け取る
        "--model",
        batch_model.as_str(),
        "--live-model",
        live_model.as_str(),
    ];
    if !title.is_empty() {
        args.push("--title");
        args.push(title.as_str());
    }
    if let Some(ref p) = materials_path {
        args.push("--materials-file");
        args.push(p.as_str());
    }
    spawn_and_relay(
        &app,
        state.inner(),
        &args,
        Relay::Summary,
        StdinMode::Feed(transcript),
    )
}

/// 清書を中断する（S-06 の「中断」）。実行中サイドカーをツリーごと終了する。
#[tauri::command]
fn abort_summarize(app: AppHandle) -> Result<(), String> {
    kill_sidecar(&app);
    Ok(())
}

/// セッションのプロセスツリーを終了する（uv とその孫 python/whisper を一掃）。
///
/// Windows では `uv`(子) を kill しても `python`/whisper(孫) が残りうる（DA-新4）。
/// `child.kill()` は直接の子(uv)しか終了させないため、`taskkill /T /F /PID` で
/// **プロセスツリーごと**確実に終了させる（孫まで reap）。
fn kill_session(mut sess: SttSession) {
    let pid = sess.child.id();
    #[cfg(windows)]
    {
        let mut tk = Command::new("taskkill");
        tk.args(["/T", "/F", "/PID", &pid.to_string()]);
        tk.creation_flags(CREATE_NO_WINDOW);
        match tk.status() {
            Ok(s) => eprintln!("[stt] taskkill tree pid={pid} -> {s}"),
            Err(e) => {
                eprintln!("[stt] taskkill failed pid={pid}: {e}; fallback child.kill()");
                let _ = sess.child.kill();
            }
        }
    }
    #[cfg(not(windows))]
    {
        match sess.child.kill() {
            Ok(_) => eprintln!("[stt] killed sidecar pid={pid}"),
            Err(e) => eprintln!("[stt] kill failed pid={pid}: {e}"),
        }
    }
}

/// 保持中のセッションを kill する（ウィンドウ破棄・アプリ終了時）。
fn kill_sidecar(app: &AppHandle) {
    // lock のガードを take() の行で確実に落とす（MutexGuard を if 本体へ持ち越すと借用エラー）。
    let taken = app.state::<SttState>().0.lock().unwrap().take();
    if let Some(sess) = taken {
        kill_session(sess);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init()) // 事前資料の選択ダイアログ（DD-012-10）
        .manage(SttState(Mutex::new(None)))
        .setup(|app| {
            // DB を開いて DbState を manage（DD-012-3 Phase 2）。失敗時は起動を止める。
            db_commands::init(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            greet,
            start_transcription,
            start_mic,
            pause_mic,
            resume_mic,
            stop_mic,
            start_level,
            start_summarize,
            abort_summarize,
            db_commands::list_meetings,
            db_commands::create_meeting,
            db_commands::complete_meeting,
            db_commands::update_meeting,
            db_commands::update_meeting_schedule,
            db_commands::delete_meeting,
            db_commands::get_meeting_detail,
            db_commands::add_attachment,
            db_commands::list_attachments,
            db_commands::remove_attachment,
            db_commands::seed_demo,
            db_commands::get_settings,
            db_commands::save_settings,
        ])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed) {
                kill_sidecar(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
