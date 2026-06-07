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

/// サイドカー(uv → python -m …sidecar)を起動し、stdout(JSON Lines)を Tauri イベントへ中継する。
///
/// 既存セッションがあれば先に kill（マイクの起動しっぱなし防止）。`want_stdin` 時は子の stdin を
/// パイプ・保持してマイクの pause/resume/stop 制御に使う。reader スレッドで即時 return。
/// 1行=1JSON を `type` で振り分け `stt-meta`/`stt-segment`/`stt-done`/`stt-error` を emit。
fn spawn_and_relay(
    app: &AppHandle,
    state: &SttState,
    args: &[&str],
    want_stdin: bool,
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
    if want_stdin {
        cmd.stdin(Stdio::piped());
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("サイドカー起動失敗(uv は PATH にある?): {e}"))?;

    let out = BufReader::new(child.stdout.take().ok_or("stdout を取得できません")?);
    let err = BufReader::new(child.stderr.take().ok_or("stderr を取得できません")?);
    let stdin = child.stdin.take(); // want_stdin の時のみ Some
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
                    let ev = match v["type"].as_str() {
                        Some("meta") => "stt-meta",
                        Some("segment") => "stt-segment",
                        Some("done") => "stt-done",
                        Some("error") => "stt-error",
                        _ => continue,
                    };
                    eprintln!("[stt] emit {ev}"); // 検証用ログ
                    let _ = app2.emit(ev, v);
                }
                Err(_) => eprintln!("[stt] non-json: {line}"), // 捨てずログ（DA-新3）
            }
        }
        eprintln!("[stt] stdout closed (sidecar finished)");
    });

    *state.0.lock().unwrap() = Some(SttSession { child, stdin });
    Ok(())
}

/// サンプル音声ファイルを文字起こし（DD-011 3-C）。stdin 制御は不要。
#[tauri::command]
fn start_transcription(
    app: AppHandle,
    state: State<'_, SttState>,
    audio_path: String,
    model: Option<String>,
) -> Result<(), String> {
    let model = model.unwrap_or_else(|| "base".into());
    let args = vec![
        "run",
        "python",
        "-m",
        "synchroni_note.pipeline.sidecar",
        audio_path.as_str(),
        "--model",
        model.as_str(),
    ];
    spawn_and_relay(&app, state.inner(), &args, false)
}

/// マイクからライブ文字起こし（DD-012-1）。`simulate` 指定時はファイルを mic 代替で流す（dev/テスト）。
/// stdin をパイプして pause/resume/stop を受け付ける。
#[tauri::command]
fn start_mic(
    app: AppHandle,
    state: State<'_, SttState>,
    model: Option<String>,
    simulate: Option<String>,
) -> Result<(), String> {
    let model = model.unwrap_or_else(|| "base".into());
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
    spawn_and_relay(&app, state.inner(), &args, true)
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
            db_commands::list_meetings,
            db_commands::create_meeting,
            db_commands::get_meeting_detail,
            db_commands::seed_demo,
        ])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed) {
                kill_sidecar(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
