# DD-011 Phase 3-C 実装前詳細化（📐）— Rust中継＋S-05ライブ配線（実ウィンドウ）

作成日	更新日	ステータス	種別
2026-06-08	2026-06-08	✅実装完了（実ウィンドウ実測OK）	DD-011 添付（Phase 3-C 実装前詳細化）
親DD: DD-011 / 上位設計: Phase3_実装前詳細化.md（サイドカー契約＝JSON Lines の全体像）。
本書は 3-C 限定の実装詳細。3-C は「新言語(Rust)×Tauri2 API×実ウィンドウでしか確認できない」最難関のため、上位設計が 「正確なTauri2 APIは実装時に確定」 と先送りした部分を着手前に確定させる。

> **実装結果（2026-06-08）**: 本設計どおり実装・実測完了。要点の差分は2つ — (1) §3 の kill は最小 `child.kill()` ではなく **`taskkill /T /F /PID` のツリーkillを採用**（孫python残存＝DA-新4を確実に解消。mid-flightクローズで uv/python 残存なしを実測）。(2) §2 の検証手段を `scripts/{shot-window,click,uia}.ps1` として実体化（AttachThreadInputで前面化→画面矩形を実ピクセルキャプチャ＝WebView2でも空白化せず／座標クリック。UIAはWebView2のDOM非公開のため座標方式）。既定ウィンドウは §6 のとおり 1200×800 へ拡大。証跡 `phase3c-s05-idle.png`／`phase3c-preparing.png`／`phase3c-timeline.png`。詳細は親DDの[Phase 3-C DA批判レビュー](../DD-011_Phase4_Tauri2ペインUI骨格_Python中身に接続.md#phase-3-c-da批判レビュー)。

0. 位置づけ（平易な要約）
3-C は「Python口（3-B）」と「画面（3-A）」を実際につなぐ最後の工程。Rustが裏でPythonサイドカーを起動し、その1行ずつのJSONを受け取って画面イベントへ中継、S-05の左タイムラインに逐次表示する。最大の懸案は「どう動作確認するか」——Playwrightは Tauri ランタイム非搭載で invoke/listen が動かないため、実ウィンドウでの確認手段を先に決める（§2）。

1. 確定した前提（実機調査・2026-06-08）
項目	実測	意味
Tauri	2.11.2	Emitter/State/on_window_event/async_runtime すべて安定版で利用可
依存	serde_json="1" あり / tauri-plugin-shell 無し	標準 std::process::Command で spawn → 権限追加・プラグイン不要（capabilities は core:default+opener:default のまま）
既定ウィンドウ	label=main、800×600	app.emit は全ウィンドウ配信で可。確認時はサイズが小さい→ §6
dev起動	tauri dev が npm run dev(vite) を自動起動（devUrl=1420）	フロントは別途起動不要
サイドカー契約	3-Bで検証済（meta/segment/done/error, UTF-8, flush）	Rustは「1行=1JSONを type で振り分け emit」するだけ
2. 検証方法（本詳細化の主目的・先に決める）
Playwright不可のため、自走で観測できるよう3層に分解する。

層	何を確認	観測方法（Claude自走）	フォールバック
Rust側	spawn→stdout読取→parse→emit	tauri dev をバックグラウンド起動し、そのコンソール出力をRead。Rustに各emitの eprintln!("[stt] emit …") を仕込み「12行読んで12回emit」を確認	（なし・確実に観測可）
画面側	timelineに逐次描画されるか	実ウィンドウをOSスクショ：PowerShellで app.exe のメインウィンドウを前面化→ウィンドウ矩形を画面キャプチャしPNG→Read	スクショが崩れる/撮れない時のみユーザに一目依頼（CLAUDE.mdの明示的例外）
後始末	閉じてプロセス残存なし	閉じた後 PowerShell で python/uv/ctranslate/whisper系プロセスの不在を確認	—
Step 0（着手の最初にやる）: 上記「OSウィンドウ・スクショ機構」を今の雛形ウィンドウで先に試し、確認手段を確立する。WebView2 はGPU合成で PrintWindow が空白になりがちなので、前面化→画面矩形キャプチャ（実ピクセル取得）を主手段にする。ここが通らなければ計画（=ユーザ目視併用）に切替える。

3. Rust 実装（app/src-tauri/src/lib.rs）— 確定API（Tauri 2.11）

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

struct SttState(Mutex<Option<Child>>);   // kill 用に Child を1つ保持

#[tauri::command]
fn start_transcription(
    app: AppHandle, state: State<'_, SttState>,
    audio_path: String, model: Option<String>,
) -> Result<(), String> {
    let py_dir = /* env!("CARGO_MANIFEST_DIR") から ../../python を絶対化（dev時） */;
    let model = model.unwrap_or_else(|| "base".into());
    let mut child = Command::new("uv")
        .current_dir(&py_dir).env("PYTHONUTF8", "1")
        .args(["run","python","-m","synchroni_note.pipeline.sidecar",&audio_path,"--model",&model])
        .stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|e| format!("サイドカー起動失敗: {e}"))?;

    let out = BufReader::new(child.stdout.take().unwrap());
    let err = BufReader::new(child.stderr.take().unwrap());
    let app2 = app.clone();

    // stderr は別スレッドでログへ（JSONに混ぜない＝DA-新3）
    std::thread::spawn(move || for line in err.lines().map_while(Result::ok) {
        eprintln!("[sidecar] {line}");
    });
    // stdout を1行ずつ → type を見て emit（reader thread・即時return）
    std::thread::spawn(move || {
        for line in out.lines().map_while(Result::ok) {
            match serde_json::from_str::<Value>(&line) {
                Ok(v) => {
                    let ev = match v["type"].as_str() {
                        Some("meta") => "stt-meta", Some("segment") => "stt-segment",
                        Some("done") => "stt-done", Some("error") => "stt-error", _ => continue,
                    };
                    eprintln!("[stt] emit {ev}");              // ← 検証用ログ
                    let _ = app2.emit(ev, v);
                }
                Err(_) => eprintln!("[stt] non-json: {line}"), // 捨てずログ（DA-新3）
            }
        }
    });

    *state.0.lock().unwrap() = Some(child);   // kill 用に保持
    Ok(())
}
登録: tauri::Builder::default().manage(SttState(Mutex::new(None)))…invoke_handler(generate_handler![greet, start_transcription])。
kill（ゾンビ対策＝DA#4/新4）: .on_window_event(|window, event| { if matches!(event, WindowEvent::CloseRequested{..} | WindowEvent::Destroyed) { /* state を取り出し child.kill() */ } })。最小は child.kill()。Windowsで孫(python/whisper)が残るなら taskkill /T /F /PID <pid>（プロセスツリーごと）に格上げ＝3-C3で実測判断。
repo/python の場所（DA-新2）: dev時は env!("CARGO_MANIFEST_DIR")（=app/src-tauri）から ../../python を canonicalize して絶対化。配布時の解決は別DD。
async にしない（reader threadで回し即return）。AppHandle は Clone+Send なので thread へ move 可。
4. フロント実装（app/src/pages/S05Realtime.vue）
import: @tauri-apps/api/core の invoke、@tauri-apps/api/event の listen（導入済の @tauri-apps/api）。
onMounted: stt-meta/segment/done/error を listen 登録（unlisten 関数を保持）、onUnmounted で解除。
「サンプルを流す」ボタン → invoke('start_transcription', { audioPath: 'audio/sample01.wav', model: 'base' })（パスは sidecar の cwd=python/ 基準の相対でよい）。
受信:
stt-meta → duration_s 保持・「文字起こし準備中」スピナー解除。
stt-segment → timeline.push({ type:'ai', speaker:'Speaker_0', t: fmtMs(t_start_ms), text, refined:null, confirmed:true })。
stt-done → 「完了」表示。 stt-error → エラー表示。
t_start_ms → "mm:ss" 整形（fmtMs）。
現行のダミー4件＋末尾「生成中」チャンクは撤去（開発フラグ ?demo で残す案も可）。
注意: 素ブラウザ(Playwright)では invoke/listen が無いのでボタンは実ウィンドウ専用。Playwrightで開いた時に例外で画面が落ちないよう、window.__TAURI__ 不在時はボタンを無効化 or ダミー投入にフォールバック。
5. 3-C の分割（リスク順に小さく＝手戻り最小化）
サブ	内容	完了条件（🔬観測）
3-C1 Rust中継（ログで確認）	start_transcription＋reader thread＋emit＋eprintln!。S-05に最小のlisten/ボタン	tauri dev コンソールに「クリック→python起動→[stt] emit ×（meta+12+done）」が出る
3-C2 画面描画＋ダミー撤去	timeline.push 描画、metaスピナー、mm:ss、ダミー撤去	OSウィンドウ・スクショで左に1行ずつ表示を確認
3-C3 後始末（kill）	Child保持＋closeでkill、必要なら taskkill /T化	閉じた後 python/uv/whisper が残らないことをPowerShellで確認。😈DA
各サブ末に 🔬機械検証、3-C3 末に 😈DA批判レビュー（最低1件）。

6. 既知の落とし穴（着手前）
メタ遅延（モデルload後にしか meta が出ない＝3-B DA①）→ base既定で短縮、UIはスピナーで吸収。
初回 tauri dev は Rustコンパイルで数分（reader thread追加で再コンパイルも）。
孫プロセス残存（Windows）＝DA-新4。3-C3で実測し必要なら taskkill /T。
WebView2 のスクショ難（GPU合成）→ §2の「前面化→画面矩形キャプチャ」で回避、最終手段はユーザ一目。
ウィンドウ 800×600 が小さい → 確認時に runtime resize か tauri.conf.json を 1200×800 程度へ。
7. 完了条件（DoD・3-C 全体）
実ウィンドウで「サンプルを流す」→ 左タイムラインに文字起こしが1行ずつ表示。
ウィンドウを閉じると python/uv/whisper が残らない（タスクマネージャ/PowerShell確認）。
DD-011 本体の 3-C チェックを更新＋3-C DA批判レビューを記録。
8. 範囲外（将来・別DD）
マイク収音（本DDはサンプル音声のみ）／話者分離の実表示（speaker 暫定固定）／LLM整形の追い上げ（refined）。
配布時の Python ランタイム同梱（PyInstaller等）＝別DD（DA#1）。
DB保存・状態遷移・Yjs/CRDT（P4-2）・ホットパスRust移植（P4-3）。
