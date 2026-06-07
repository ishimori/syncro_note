// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};

// SQLite データアクセス層（DD-012-3）。frontend への Tauri command 公開は Phase 2 で行う。
#[allow(dead_code)]
mod db;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000; // uv のコンソール窓が一瞬出るのを抑止

/// 起動中の Python サイドカー(子プロセス)を1つ保持する。ウィンドウ破棄時の kill 用（DA#4/新4）。
struct SttState(Mutex<Option<Child>>);

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

/// サンプル音声を Python サイドカーで文字起こしし、JSON Lines を Tauri イベントへ中継する。
///
/// 即時 return（reader スレッドで stdout を1行ずつ読み続ける）。1行=1JSON を `type` で振り分け、
/// `stt-meta` / `stt-segment` / `stt-done` / `stt-error` を全ウィンドウへ emit する。
#[tauri::command]
fn start_transcription(
    app: AppHandle,
    state: State<'_, SttState>,
    audio_path: String,
    model: Option<String>,
) -> Result<(), String> {
    let py_dir = repo_python_dir()?;
    let model = model.unwrap_or_else(|| "base".into());

    let mut cmd = Command::new("uv");
    cmd.current_dir(&py_dir)
        .env("PYTHONUTF8", "1") // 文字化け保険（DA#2）
        .args([
            "run",
            "python",
            "-m",
            "synchroni_note.pipeline.sidecar",
            &audio_path,
            "--model",
            &model,
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("サイドカー起動失敗(uv は PATH にある?): {e}"))?;

    let out = BufReader::new(child.stdout.take().ok_or("stdout を取得できません")?);
    let err = BufReader::new(child.stderr.take().ok_or("stderr を取得できません")?);
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

    *state.0.lock().unwrap() = Some(child); // kill 用に保持
    Ok(())
}

/// 保持中の子プロセスを kill する（ウィンドウ破棄・アプリ終了時）。
fn kill_sidecar(app: &AppHandle) {
    let state = app.state::<SttState>();
    // lock のガードを take() の行で確実に落とす（MutexGuard を if 本体へ持ち越すと
    // state より長生きして借用エラーになる）。
    let taken = state.0.lock().unwrap().take();
    if let Some(mut child) = taken {
        let pid = child.id();
        match child.kill() {
            Ok(_) => eprintln!("[stt] killed sidecar pid={pid}"),
            Err(e) => eprintln!("[stt] kill failed pid={pid}: {e}"),
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(SttState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![greet, start_transcription])
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed) {
                kill_sidecar(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
