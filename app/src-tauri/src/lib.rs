// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Mutex, OnceLock};

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

/// 配布時に同梱した sidecar 実行ファイルの絶対パス（無ければ `None`＝開発時で uv 経路）。
/// setup で一度だけ解決する（DD-012-6: 開発=uv / 配布=同梱exe の起動切替の唯一の分岐点）。
static SIDECAR_EXE: OnceLock<Option<PathBuf>> = OnceLock::new();

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

/// サイドカー起動の基底コマンドを生成する（DD-012-6: 配布パッケージングの唯一の分岐点）。
///
/// - 配布時: 同梱した単一exe（`SIDECAR_EXE`）を `exe <module> <module固有引数...>` で起動する。
///   exe 側は第1引数 `module` で sidecar / summarize_sidecar / calendar_parse_sidecar を振り分ける
///   （`pipeline.dist_entry`）。
/// - 開発時: `uv run python -m synchroni_note.pipeline.<module> <module固有引数...>`（従来どおり）。
///
/// どちらの経路でもフロントとの契約（stdin/stdout の JSON Lines）は不変（DD-011 DA#1）。
/// `PYTHONUTF8` とコンソール窓抑止（Windows）はここで一括設定する。呼び出し側は戻り値へ
/// module 固有の引数と stdio を足して spawn する。
fn sidecar_base(module: &str) -> Result<Command, String> {
    let mut cmd = match SIDECAR_EXE.get().and_then(|o| o.as_ref()) {
        // 配布: 同梱 exe。第1引数 module で dist_entry が対象 sidecar へ振り分ける。
        Some(exe) => {
            let mut c = Command::new(exe);
            c.arg(module);
            c
        }
        // 開発（未解決を含む）: uv 経由でモジュール実行。uv が PATH に要る。
        None => {
            let py_dir = repo_python_dir()?;
            let mut c = Command::new("uv");
            c.current_dir(&py_dir)
                .args(["run", "python", "-m"])
                .arg(format!("synchroni_note.pipeline.{module}"));
            c
        }
    };
    cmd.env("PYTHONUTF8", "1"); // 文字化け保険（DA#2）
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    Ok(cmd)
}

/// 配布物に同梱した sidecar exe を探す（DD-012-6）。見つからなければ `None`＝開発(uv)経路。
///
/// 探索順:
/// 1. 環境変数 `SYNCHRONI_SIDECAR_EXE`（手動上書き。exe ビルド前でも切替経路を検証できる）。
/// 2. Tauri の resource_dir 配下（配布物に同梱した実体）。
///
/// resource 配下の配置名（`sidecar/synchroni-sidecar.exe`）は仮。PyInstaller の実ビルド時に
/// `tauri.conf.json` の `bundle.resources` と突き合わせて確定する（DD-012-6 Phase1）。
fn resolve_sidecar_exe(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(p) = std::env::var("SYNCHRONI_SIDECAR_EXE") {
        let path = PathBuf::from(p);
        if path.is_file() {
            eprintln!("[sidecar] exe(env)= {}", path.display());
            return Some(path);
        }
    }
    let cand = app
        .path()
        .resource_dir()
        .ok()?
        .join("sidecar")
        .join("synchroni-sidecar.exe");
    cand.is_file().then(|| {
        eprintln!("[sidecar] exe(resource)= {}", cand.display());
        cand.clone()
    })
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
    let mut cmd = sidecar_base("sidecar")?;
    cmd.args(["--extract", path]);
    if let Some(t) = file_type {
        cmd.args(["--type", t]);
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

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

/// カレンダー予定テキストを qwen で構造化する（DD-012-13）。
///
/// `calendar_parse_sidecar` を**同期(ブロッキング)実行**し、予定テキストを stdin で渡して
/// 1行の `type=calendar-parse` JSON を受け取る。`extract_text_blocking`（DD-012-10）と同じ
/// 一発取り契約だが、入力が長文テキストなので引数ではなく stdin から流す（行長・引用符の問題回避）。
/// 戻り値は draft オブジェクト（title/scheduled_start/scheduled_end/place/agenda/participants/year_inferred）。
#[tauri::command]
fn parse_calendar_text(text: String) -> Result<Value, String> {
    if text.trim().is_empty() {
        return Err("予定テキストが空です".to_string());
    }
    let mut cmd = sidecar_base("calendar_parse_sidecar")?;
    cmd.arg("-"); // 予定テキストは stdin から受け取る
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("取込サイドカー起動失敗(uv は PATH にある?): {e}"))?;
    {
        // stdin を閉じる（drop）まで Python は読み続ける。ブロックを抜けて drop=EOF を送る。
        let mut stdin = child.stdin.take().ok_or("stdin を開けません")?;
        stdin
            .write_all(text.as_bytes())
            .map_err(|e| format!("stdin 書き込み失敗: {e}"))?;
    }
    let output = child
        .wait_with_output()
        .map_err(|e| format!("取込サイドカー待機失敗: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    // 末尾から type=calendar-parse の行を拾う（前段に uv 警告が出ても無視）。
    for line in stdout.lines().rev() {
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if v.get("type").and_then(|t| t.as_str()) == Some("calendar-parse") {
            return match v.get("status").and_then(|s| s.as_str()) {
                Some("done") => v.get("draft").cloned().ok_or_else(|| "draft 欠落".to_string()),
                _ => Err(v
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("予定の解析に失敗しました")
                    .to_string()),
            };
        }
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!("解析結果(JSON)を取得できません: {}", stderr.trim()))
}

/// 入力デバイス一覧をサイドカー（`--list-devices`）から**同期(ブロッキング)取得**する（DD-012-14）。
///
/// `extract_text_blocking`（DD-012-10）と同じ一発取り契約。返りは items 配列
/// （`{index,name,hostapi,max_input_channels,default}`）。UIのデバイス選択と名前→番号解決で使う。
fn list_input_devices_blocking() -> Result<Vec<Value>, String> {
    let mut cmd = sidecar_base("sidecar")?;
    cmd.arg("--list-devices");
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let output = cmd
        .output()
        .map_err(|e| format!("デバイス列挙サイドカー起動失敗(uv は PATH にある?): {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    // 末尾から type=devices の行を拾う（前段に uv 警告が出ても無視）。
    for line in stdout.lines().rev() {
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if v.get("type").and_then(|t| t.as_str()) == Some("devices") {
            if v.get("status").and_then(|s| s.as_str()) == Some("done") {
                return Ok(v
                    .get("items")
                    .and_then(|i| i.as_array())
                    .cloned()
                    .unwrap_or_default());
            }
            return Err(v
                .get("message")
                .and_then(|m| m.as_str())
                .unwrap_or("デバイス列挙に失敗しました")
                .to_string());
        }
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(format!("デバイス一覧(JSON)を取得できません: {}", stderr.trim()))
}

/// 入力デバイス一覧を返す（S-04/S-08 のプルダウン用・DD-012-14）。
#[tauri::command]
fn list_input_devices() -> Result<Vec<Value>, String> {
    list_input_devices_blocking()
}

/// 設定の `mic_device`(名前) を sounddevice の device index に解決する（DD-012-14）。
///
/// 未設定／一覧に一致なし／列挙失敗のいずれも `None`＝OS既定デバイスにフォールバックし、
/// 計測・録音を止めない（抜き差しでデバイスが消えても安全側に倒す）。
/// 照合は**完全一致のみ**: 保存名は UI が同じ列挙の `name` をそのまま書くため `==` で必ず当たる。
/// 前方一致は別マイクの取り違え（例: 「マイク」と「マイク 2」）を生むため使わない（DD-012-14 レビュー）。
fn resolve_mic_device(app: &AppHandle) -> Option<i64> {
    let want = {
        let state = app.state::<db_commands::DbState>();
        let conn = state.0.lock().ok()?;
        db::get_settings(&conn).ok()?.mic_device? // conn はこのブロックを抜けて解放（列挙の子プロセス前に手放す）
    };
    let want = want.trim();
    if want.is_empty() {
        return None;
    }
    let items = list_input_devices_blocking().ok()?;
    for it in &items {
        let name = it.get("name").and_then(|n| n.as_str()).unwrap_or("");
        if name == want {
            return it.get("index").and_then(|i| i.as_i64());
        }
    }
    eprintln!("[mic] 設定のデバイス '{want}' が一覧に無いためOS既定にフォールバック");
    None
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

/// サイドカー(開発=uv → python -m … / 配布=同梱exe)を起動し、stdout(JSON Lines)を Tauri イベントへ中継する。
///
/// 既存セッションがあれば先に kill（起動しっぱなし防止）。`module` は pipeline 下のモジュール名
/// （sidecar / summarize_sidecar 等）、`module_args` はそのモジュール固有の引数。起動経路の差
/// （uv / 同梱exe）は `sidecar_base` に集約（DD-012-6）。`stdin_mode` で stdin の扱いを切替える
/// （保持して制御 / 一括投入して EOF / 不要）。`relay` で emit するイベント名の系統（stt-* /
/// summary-*）を選ぶ。reader スレッドで即時 return。
fn spawn_and_relay(
    app: &AppHandle,
    state: &SttState,
    module: &str,
    module_args: &[&str],
    relay: Relay,
    stdin_mode: StdinMode,
) -> Result<(), String> {
    // 進行中セッションがあれば先に終了（start→start での取り残し防止）。
    let prev = state.0.lock().unwrap().take();
    if let Some(sess) = prev {
        kill_session(sess);
    }

    // 起動経路（開発=uv / 配布=同梱exe）は sidecar_base に集約（DD-012-6）。PYTHONUTF8 と
    // コンソール窓抑止（Windows）もそこで設定済み。
    let mut cmd = sidecar_base(module)?;
    cmd.args(module_args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if !matches!(stdin_mode, StdinMode::None) {
        cmd.stdin(Stdio::piped());
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("サイドカー起動失敗(uv/同梱exe を確認): {e}"))?;

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
        audio_path.as_str(),
        "--model",
        model.as_str(),
        "--threads",
        threads.as_str(),
    ];
    spawn_and_relay(&app, state.inner(), "sidecar", &args, Relay::Stt, StdinMode::None)
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
    tv_mode: Option<bool>,
) -> Result<(), String> {
    // テレビモード（DD-017-4・方針A）: 録音中のライブ逐次話者分離(--live-diarize)を有効化し、
    // フルパワー配分（DD-017-3）として threads を 8 に上書き＋ライブLLM整形を無効化（CPUをSTTへ）。
    let tv = tv_mode.unwrap_or(false);
    let (cfg_model, cfg_threads) = stt_settings(&app);
    let model = model.unwrap_or(cfg_model); // S-08 設定の STT モデル（DD-012-7）
    let threads = if tv { "8".to_string() } else { cfg_threads.to_string() };
    // テレビモード時は整形を回さない（STT+LLM 同時実行で RTF 破綻するため・DD-003/017-3）。
    let refine_model = if tv { None } else { live_refine_model(&app, refine) };
    // 収音デバイス: 設定 mic_device(名前)→番号に解決（DD-012-14）。simulate 時は不要。None＝OS既定。
    let dev_str = if simulate.is_none() {
        resolve_mic_device(&app).map(|d| d.to_string())
    } else {
        None
    };
    eprintln!(
        "[stt] mic model={model} threads={threads} simulate={} refine={} tv={tv} device={}",
        simulate.is_some(),
        refine_model.is_some(),
        dev_str.as_deref().unwrap_or("default"),
    );
    let mut args: Vec<&str> = Vec::new();
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
    if tv {
        args.push("--live-diarize"); // 録音中ローリング再分離（DD-017-2）
    }
    if let Some(d) = dev_str.as_deref() {
        args.push("--device");
        args.push(d);
    }
    if let Some(live) = refine_model.as_deref() {
        args.push("--refine");
        args.push("--live-model");
        args.push(live);
    }
    spawn_and_relay(&app, state.inner(), "sidecar", &args, Relay::Stt, StdinMode::Control)
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
    device: Option<i64>,
) -> Result<(), String> {
    // 明示指定（UIがプルダウンの番号を渡す）を優先、無ければ設定の mic_device 名から解決（DD-012-14）。
    let dev = device.or_else(|| resolve_mic_device(&app));
    let dev_str = dev.map(|d| d.to_string());
    let mut args: Vec<&str> = vec!["--level"];
    if let Some(path) = simulate.as_deref() {
        args.push("--simulate");
        args.push(path);
    }
    if let Some(d) = dev_str.as_deref() {
        args.push("--device");
        args.push(d);
    }
    spawn_and_relay(&app, state.inner(), "sidecar", &args, Relay::Stt, StdinMode::Control)
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

/// 会議の専門用語をカンマ区切りで返す（清書プロンプトの「専門用語」へ・DD-012-12 Bug#7）。無ければ None。
fn gather_vocab(app: &AppHandle, meeting_id: &str) -> Option<String> {
    let words = {
        let state = app.state::<db_commands::DbState>();
        let conn = state.0.lock().ok()?;
        db::list_vocabularies(&conn, meeting_id).ok()?
    };
    if words.is_empty() {
        return None;
    }
    Some(words.join(","))
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
    // 専門用語（Bug#7）: meeting_id があれば vocab をカンマ区切りで清書へ渡す。
    let vocab_csv = meeting_id.as_deref().and_then(|id| gather_vocab(&app, id));
    eprintln!(
        "[summary] start batch={batch_model} live={live_model} chars={} materials={} vocab={}",
        transcript.len(),
        materials_path.is_some(),
        vocab_csv.is_some()
    );
    let mut args: Vec<&str> = vec![
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
    if let Some(ref v) = vocab_csv {
        args.push("--vocab");
        args.push(v.as_str());
    }
    spawn_and_relay(
        &app,
        state.inner(),
        "summarize_sidecar",
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

/// セッションのプロセスツリーを終了する（開発=uv とその孫 python/whisper、配布=同梱exe とその子を一掃）。
///
/// Windows では親(uv / 同梱exe) を kill しても子孫(python/whisper)が残りうる（DA-新4）。
/// `child.kill()` は直接の子しか終了させないため、`taskkill /T /F /PID` で
/// **プロセスツリーごと**確実に終了させる（孫まで reap）。配布の同梱exe経路でも PID ツリー
/// kill なので同じく有効（DD-012-6）。
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
            // DD-016-2/案C: 前回の未保存 ad-hoc 仮会議（録音中だけ status='active' で仮作成し、
            // 保存されずに残ったもの）を起動時に掃除する。失敗は致命的でないのでログのみ。
            {
                let state = app.state::<db_commands::DbState>();
                // ロックガードを内側ブロックで落としてから（所有値 Result を取り出す）結果を処理する。
                let swept = match state.0.lock() {
                    Ok(conn) => {
                        // 添付のコピー済み物理ファイルを先に後始末（CASCADE は DB 行のみ消す・DD-016 レビュー）。
                        if let Ok(paths) = crate::db::list_unsaved_adhoc_attachment_paths(&conn) {
                            for p in paths {
                                let _ = std::fs::remove_file(p); // best-effort
                            }
                        }
                        crate::db::delete_unsaved_adhoc_meetings(&conn)
                    }
                    Err(_) => Ok(0),
                };
                match swept {
                    Ok(n) if n > 0 => eprintln!("[db] swept {n} unsaved ad-hoc meeting(s)"),
                    Ok(_) => {}
                    Err(e) => eprintln!("[db] sweep failed: {e}"),
                }
            }
            // DD-012-6: 配布時に同梱した sidecar exe を解決し、以降の起動経路を切替える
            // （開発時は見つからず None＝uv 経路）。解決は一度だけ。
            let _ = SIDECAR_EXE.set(resolve_sidecar_exe(app.handle()));
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
            list_input_devices,
            start_summarize,
            abort_summarize,
            parse_calendar_text,
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
