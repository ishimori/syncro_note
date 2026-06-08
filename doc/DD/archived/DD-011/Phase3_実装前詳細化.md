# DD-011 Phase 3 実装前詳細化（📐）— Python中身に接続（サイドカー設計）

| 作成日 | 更新日 | ステータス | 種別 |
|--------|--------|------------|------|
| 2026-06-07 | 2026-06-07 | 設計（実装前・👀レビュー待ち） | DD-011 添付（Phase 3 実装前詳細化） |

> 親DD: [DD-011（Phase4 Tauri 2ペインUI骨格 — Python中身に接続）](../DD-011_Phase4_Tauri2ペインUI骨格_Python中身に接続.md)
> 本ファイルは DD-011 のタスク「Phase 3 → 📐 実装前詳細化」の中身。**実装はまだ行わない**。本書を 👀 レビューしてからコーディングに入る。
> **（2026-06-08 追記）** Phase 3 は **3-A/3-B/3-C に再編**。本書が扱うサイドカー接続は **3-B（Python実行口・CLI単体確認）＋3-C（Rust中継＋S-05ライブ配線・実ウィンドウ）** に対応（3-A=全画面シェルは別途完了）。§9の作業順のうち「Python実行口」が3-B、「Rust中継／フロント」が3-C。

---

## 0. このファイルの位置づけ（平易な要約）

Phase 3 は「**今あるPythonの文字起こし**」と「**Phase 2で作った画面**」を初めて1本の線でつなぐ工程。サンプル音声を入れると、文字起こし結果が画面の左に**1行ずつ流れて出る**——そこまでを通す。

つなぎ方は DD 決定済みの**サイドカー方式**（案A）: Python を裏方（子プロセス）として起動し、その出力を Rust が受け取って画面へ中継する。

調査の結論として、**両端の受け入れ態勢はほぼ整っている**（§1）。Phase 3 は新規発明ではなく「**既にある逐次出力を画面まで配線する**」作業。

## 1. 調査でわかった現状（両端の受け入れ態勢）

| 場所 | 状態 | Phase 3 での意味 |
|---|---|---|
| Python `stream_transcribe()` | セグメントを**1件ずつ返す**形が既にある（[transcribe.py:33](../../../python/src/synchroni_note/pipeline/transcribe.py)） | 中身はそのまま使える。**「1行ずつ吐く薄い口」を足すだけ** |
| Python `Segment` | `text / t_start_ms / t_end_ms` の3フィールド（[transcribe.py:16](../../../python/src/synchroni_note/pipeline/transcribe.py)） | 契約スキーマはこの3つが土台。話者・整形は持たない＝Phase 3範囲外と整合 |
| Python `cli.py` | `sys.stdout.reconfigure(encoding="utf-8")` 済み（[cli.py:86](../../../python/src/synchroni_note/pipeline/cli.py)） | 文字化け対策（DA#2）の手本が既にある |
| 画面 `timeline` | `reactive` 配列に push すれば増える作り。今はダミー4件＋末尾「生成中」が固定（[S05Realtime.vue:57](../../../app/src/pages/S05Realtime.vue)） | 受信したら push するだけ。**受け口OK**。ダミーは撤去する |
| フロント依存 | `@tauri-apps/api` 導入済み（[package.json:14](../../../app/package.json)） | Rustからのイベントを**待ち受け可能**（追加導入不要） |
| Rust `lib.rs` | 雛形のまま（`greet`だけ）。`serde_json` は依存に有り（[Cargo.toml:24](../../../app/src-tauri/Cargo.toml)） | 中継処理はこれから書く。**`tauri-plugin-shell` は未導入** |
| 権限 `capabilities/default.json` | `core:default` / `opener:default` のみ | Rust標準のプロセス起動を使えば**権限追加は不要**（§4の方式選定の根拠） |
| サンプル音声 | `python/audio/sample01.wav` / `sample02.wav` あり | **検証できる**（マイクは範囲外でOK） |

## 2. 全体のデータの流れ

```
[サンプル音声 .wav]
      │
      ▼  (1) フロントが invoke('start_transcription', { audioPath, model })
┌──────────────────────────── Tauri (Rust) ────────────────────────────┐
│  (2) 子プロセス起動:  uv run python -m synchroni_note.pipeline.sidecar │
│        cwd = <repo>/python   env: PYTHONUTF8=1                         │
│  (3) 子の stdout を1行ずつ読む（BufReader::lines）                      │
│  (4) 1行=1JSON を判定し、対応する Tauri イベントへ emit                 │
│        stderr は別スレッドでログへ（JSONに混ぜない）                    │
│  (5) child を State に保持 → ウィンドウ破棄/終了時に kill               │
└───────────────────────────────────────────────────────────────────────┘
      │  emit: stt-meta / stt-segment / stt-done / stt-error
      ▼  (6) フロントが listen して受信
[ S-05 画面 ] timeline.push(...) → 左ペインに1行ずつ表示
```

裏方Python ── **JSON Lines契約**（§3）── Rust中継（§4）── 画面表示（§5）。
この**契約を挟む**のが肝で、将来 Python を高速なRust製STTに差し替えても画面側は無改修で済む（DA#1の「配布時Python同梱」を別DDへ切り出せる理由）。

## 3. サイドカー契約（JSON Lines スキーマ）

裏方は「**1行＝1メッセージのJSON**（改行区切り、UTF-8）」で話す。種類を `type` で区別する。

```jsonc
{"v":1,"type":"meta","duration_s":123.4,"model":"medium","language":"ja"}   // 最初に1回
{"v":1,"type":"segment","seq":0,"text":"お疲れ様です。","t_start_ms":1230,"t_end_ms":4560}
{"v":1,"type":"segment","seq":1,"text":"本日は…","t_start_ms":4600,"t_end_ms":8000}
{"v":1,"type":"done","count":42,"elapsed_s":58.2}                            // 最後に1回
{"v":1,"type":"error","message":"audio file not found","where":"open"}       // 異常時のみ
```

| type | 出るタイミング | フィールド | 用途 |
|------|----------------|-----------|------|
| `meta` | 開始直後に1回 | `duration_s`（音声長・即時判明）, `model`, `language` | 画面の「準備中」解除・進捗分母。**初動の無音対策の要**（DA-新1） |
| `segment` | 文字起こし1件ごと | `seq`（0始まり連番）, `text`, `t_start_ms`, `t_end_ms` | 左ペインへ1行追記 |
| `done` | 全完了で1回 | `count`（総数）, `elapsed_s` | 「完了」表示 |
| `error` | 異常時のみ | `message`, `where`（任意・発生箇所） | エラー表示。出したら異常終了 |

- 全メッセージに `"v":1`（スキーマ版）を持たせ、将来の契約変更に備える。
- **話者（speaker）・LLM整形（refined）は Phase 3 では出さない**（`Segment` が持たない＝範囲外と整合）。画面側は暫定で「`Speaker_0` 固定／整形なし」で表示する。
- `seq` はフロントの重複排除・並べ替えの保険（基本は到着順でよい）。
- 進捗バーは `t_end_ms / (duration_s*1000)` で画面側が計算できるので、専用の progress メッセージは作らない。

## 4. Python側 — 薄い実行口

### 置き場と起動
- 新規モジュール: `python/src/synchroni_note/pipeline/sidecar.py`（責務は「UI皮への中継」。議事録Markdownを作る `cli.py` とは目的が違うので分ける）。
- 起動コマンド（開発時）: `uv run python -m synchroni_note.pipeline.sidecar <audio> [--model medium] [--language ja]`
  - `pyproject.toml` の `[project.scripts]` への登録は**任意**（`python -m` で呼べるため、まずは登録しない）。
- 配布用 exe への同梱は**やらない**（DA#1＝別DD）。本DDは `uv run` 直叩きで疎通のみ確認する。

### 実装方針（擬似コード・設計説明用）
```python
# sidecar.py（イメージ。実装は👀レビュー後）
import sys, json, argparse, time
from pathlib import Path

def emit(obj: dict) -> None:
    # 1行=1JSON。ensure_ascii=False で日本語をそのまま。毎行 flush で逐次性を担保（DA#3）。
    print(json.dumps({"v": 1, **obj}, ensure_ascii=False), flush=True)

def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # cp932回避（DA#2、cli.py と同じ手当て）
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--model", default="medium")
    ap.add_argument("--language", default="ja")
    args = ap.parse_args(argv)
    try:
        from synchroni_note.pipeline.transcribe import stream_transcribe
        stream = stream_transcribe(args.audio, model_size=args.model, language=args.language)
        emit({"type": "meta", "duration_s": stream.duration_s,
              "model": args.model, "language": args.language})
        t0, n = time.perf_counter(), 0
        for seg in stream.segments:                 # ← 既存の逐次ジェネレータをそのまま使う
            emit({"type": "segment", "seq": n, "text": seg.text,
                  "t_start_ms": seg.t_start_ms, "t_end_ms": seg.t_end_ms})
            n += 1
        emit({"type": "done", "count": n, "elapsed_s": time.perf_counter() - t0})
    except Exception as e:                          # 異常は error で通知＋stderrにも残す
        emit({"type": "error", "message": str(e), "where": "transcribe"})
        print(f"[sidecar] {e!r}", file=sys.stderr, flush=True)
        return 1
    return 0
```
- ポイント: **既存 `stream_transcribe` の逐次出力をそのまま流すだけ**。新規ロジックは「JSONで包んで1行ずつ吐く」薄い層のみ。
- 警告・ログの類は **stderr** へ。stdout は JSON 専用に保つ（Rust側パースの汚染防止＝DA-新3）。

## 5. Rust側 — 起動と中継

### 方式の選定
| 方式 | 内容 | 評価 |
|------|------|------|
| **(b) Rust標準 `std::process::Command`＋読み取りスレッド（採用）** | 子プロセスを起動し、stdoutをBufReaderで1行ずつ読み `app.emit()` で中継 | ✅ プラグイン/権限の追加が不要。開発時の `uv run` 直叩きと相性が良い。kill制御も自前で明確 |
| (a) `tauri-plugin-shell` の Command/sidecar | プラグインのCommand APIで起動 | ❌ 今は過剰。sidecarは externalBin（同梱exe）前提が強く、任意コマンド許可の capability 設定も要る。配布DDで再検討 |

→ **(b) を採用**。`tauri::async_runtime`（Tauri内蔵）でstdout読み取りを回し、`AppHandle::emit` でフロントへ送る。

### Tauri コマンドとイベント名
- コマンド: `#[tauri::command] async fn start_transcription(app: AppHandle, state, audio_path: String, model: Option<String>) -> Result<(), String>`
- イベント名（規約を統一）: `stt-meta` / `stt-segment` / `stt-done` / `stt-error`

### 実装方針（擬似コード・設計説明用）
```rust
// lib.rs（イメージ。正確なTauri2 APIは実装時に確定）
#[tauri::command]
async fn start_transcription(app: AppHandle, state: State<'_, Child地保持>,
                             audio_path: String, model: Option<String>) -> Result<(), String> {
    let mut child = Command::new("uv")
        .current_dir(repo_python_dir())                 // cwd=<repo>/python（DA-新2）
        .env("PYTHONUTF8", "1")                          // 文字化け保険（DA#2）
        .args(["run", "python", "-m", "synchroni_note.pipeline.sidecar",
               &audio_path, "--model", model.as_deref().unwrap_or("medium")])
        .stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|e| e.to_string())?;

    let out = BufReader::new(child.stdout.take().unwrap());
    let err = BufReader::new(child.stderr.take().unwrap());
    state.store(child);                                  // ← kill 用に保持（§5 ゾンビ対策）

    // stderr は別スレッドでログへ（JSONに混ぜない）
    spawn(move || for line in err.lines().flatten() { log::warn!("[sidecar] {line}"); });

    // stdout を1行ずつ → type を見て emit
    for line in out.lines().flatten() {
        match serde_json::from_str::<Value>(&line) {
            Ok(v) => { let ev = match v["type"].as_str() {
                          Some("meta") => "stt-meta", Some("segment") => "stt-segment",
                          Some("done") => "stt-done", Some("error") => "stt-error", _ => continue };
                       let _ = app.emit(ev, v); }
            Err(_) => log::warn!("non-json line: {line}"),   // パース失敗は捨てずログ（DA-新3）
        }
    }
    Ok(())
}
```

### 子プロセスの後始末（ゾンビ対策＝DA#4 ＋ DA-新4）
- 起動した `Child` を `tauri::State<Mutex<Option<Child>>>` に保持する。
- `WindowEvent::Destroyed` / アプリ終了で **kill** する。
- Windows では子(`uv`)を消しても**孫(whisperワーカ)が残りうる**。最小実装は `child.kill()`、確実版は**プロセスツリーごと終了**（Job Object もしくは `taskkill /T /F /PID`）。Phase 3 では最小実装＋「孫プロセス残存」を DA に明記して後続で確実版へ。

## 6. フロント側 — 逐次表示（S-05）

- `@tauri-apps/api/event` の `listen`、`@tauri-apps/api/core` の `invoke` を使う。
- `onMounted` で4イベントを `listen` 登録、`onUnmounted` で `unlisten`。
- **開始トリガー**: 画面に「サンプルを流す」ボタンを置き、`invoke('start_transcription', { audioPath, model })` を呼ぶ（マイクは範囲外なのでパスは固定のサンプルでよい）。
- 受信時の処理:
  - `stt-meta` → `duration_s` を保持し「準備中」スピナーを解除。
  - `stt-segment` → `timeline.push({ type:'ai', speaker:'Speaker_0', t: fmtMs(t_start_ms), text, refined:null, confirmed:false })`。
  - `stt-done` → 「完了」表示。`stt-error` → エラー表示。
- 時刻表示は `t_start_ms` → `"mm:ss"` に整形。
- 現在ハードコードされている**ダミー4件と末尾「生成中」チャンクは撤去**（必要なら開発用フラグで残す）。
- 注意: 素のブラウザ（Playwright）には Tauri ランタイムが無く `listen`/`invoke` が動かない → **実ウィンドウで確認**（Phase 3 は Playwright 不可）。

## 7. 異常系の扱い

| ケース | 起こること | 対応 |
|---|---|---|
| 音声ファイルが無い | Python が `error` を出して終了 | 画面にエラー表示。Rustは child 終了を検知 |
| `uv` が見つからない/起動失敗 | spawn が失敗 | `start_transcription` が `Err` を返し、画面に「起動できません」表示 |
| 非JSON行が来る | stdout に想定外出力 | パース失敗としてログのみ（画面は止めない＝DA-新3） |
| 途中でウィンドウを閉じる | 子・孫が残る恐れ | §5 の kill で終了（DA#4／DA-新4） |

## 8. DA先出し（着手前に潰す落とし穴）

### 既知（Phase 0 DA で対応予定だったもの）
| # | 落とし穴 | 本設計での対応 |
|---|---------|----------------|
| DA#1 | 配布時のPython同梱が重い | **別DDへ分離**。本DDは `uv run` 直叩き。契約(JSON Lines)を挟むので後で同梱exeに差し替えても無改修 |
| DA#2 | Windowsの文字化け（cp932） | Python: `stdout.reconfigure(utf-8)`／Rust: `PYTHONUTF8=1`＋UTF-8で読む |
| DA#3 | stdoutの溜め込みで逐次にならない | 各行 `flush=True`＋1行=1JSON（必要なら `python -u`） |
| DA#4 | 子プロセスがゾンビ化 | `Child` を保持し終了時 kill（§5） |

### 新たに気づいた点
| # | 落とし穴 | 重要度 | 対応 |
|---|---------|--------|------|
| 新1 | **初動が無音に見える**：モデル読込で最初の `segment` まで数秒〜数十秒空く | 中 | `meta` を先に出し、画面は「文字起こし準備中」スピナーを表示。`duration_s` で分母も確保 |
| 新2 | **`uv` の作業場所/PATH**：Rustから呼ぶとき cwd を `python/` にしないと pyproject を見つけられない | 中 | 絶対パス＋`current_dir(<repo>/python)` 明示。`uv` 不在環境は配布DDの領域 |
| 新3 | **stderr の混入**：whisperの警告がJSONに混ざるとパース崩壊 | 中 | stdout/stderr を分離して読む。非JSON行はログのみで握りつぶさない |
| 新4 | **孫プロセス残存（Windows）**：`uv`を消しても whisper が残りうる | 中 | 最小は `child.kill()`、確実版はプロセスツリーごと終了（Job Object/`taskkill /T`）。確実版は後続でも可 |

## 9. 作業の順番・完了条件・検証

### 作業順
1. 📐 本書を 👀 レビュー（契約・置き場・イベント名・kill方針の合意）
2. Python実行口（`sidecar.py`）を追加
3. Rust中継（`start_transcription` ＋ stdout読み取り＋emit＋kill）
4. フロント（listen＋timeline push＋開始ボタン＋ダミー撤去）
5. 🔬 機械検証（下記）
6. 😈 DA批判レビュー（最低1件）

### 完了条件（DoD）
- 実ウィンドウで「サンプルを流す」→ **左ペインに文字起こしが1行ずつ表示**される。
- ウィンドウを閉じると裏方プロセスが残らない（タスクマネージャで確認）。

### 検証手順（Playwright不可・実ウィンドウ）
1. `cd app && npm run tauri dev` で起動（事前にポート1420を解放：`Get-NetTCPConnection -LocalPort 1420 | Stop-Process -Force`）。
2. 「サンプルを流す」→ `python/audio/sample01.wav` を指定。
3. 左ペインに逐次表示されるのを**連続スクショ or 録画**で証跡化（`DD-011/` に保存）。
4. ウィンドウを閉じ、`python`/`uv` プロセスが残っていないことを確認。

※ RTF（処理が音声に間に合うか）は DD-010 で実測済みのため、本検証の主眼は「**経路が通ること**」。

## 10. 範囲外（将来・別DD）

- 配布時の Python ランタイム同梱（PyInstaller等）＝**別DD**（DA#1）。
- マイクからのリアルタイム収音（本DDはサンプル音声のみ）。
- 話者分離の表示（`speaker` は暫定固定。DD-004系の成果を後で接続）。
- LLM整形の「追い上げ表示」（`refined`）。
- DB保存・状態遷移・同時編集（Yjs/CRDT＝P4-2）・ホットパスのRust移植（P4-3）。
