# DD-012-4: LLM追い上げ整形のライブ表示

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 完了（Phase 0-2・実マイクで追い上げ表示を確認・DoD達成） |

> 親DD: [DD-012 製品化（中核機能の実装と実用化）](DD-012_製品化_中核機能の実装と実用化.md)
> アプローチ: 標準（探索的実装。基本設計の「非ブロッキング追い上げ」原則に従う）

## 目的

確定文字起こし（主役）を止めずに、**live `qwen3:8b` でケバ取り/語尾整えを後追い**し、S-05 の薄字 `refined` レイヤに遅れて表示する。整形が遅れても主役は崩れない設計を実装する。

## 背景・課題

- 基本設計SSOTの再フレーム＝「**確定テキストが主役・LLM整形は遅れてよい追い上げレイヤ**」。S-05 には既に `refined` 表示スロット・`unrefined` バッジ・ON/OFFトグルがある（[app/src/pages/S05Realtime.vue](../../app/src/pages/S05Realtime.vue)）。
- モデルは DD-002 で `qwen3:8b`（TTFT 0.39秒最速・日本語固有名詞補正に強い）に決着。

## 検討内容

- 整形は**非ブロッキング**（STTと時間分離。STTを詰まらせない）。詰まり時は整形バイパス（S-05 にバナー有）。
- サイドカー契約に `refined`（seq対応）を追加。フロントは該当 seq の行に後追いで差し込む。

## スコープ

- **やる**: 確定セグメント→qwen3:8b整形→S-05 の該当行へ refined 差し込み。ON/OFFトグル・バイパス表示の結線。
- **やらない**: 終了後のバッチ清書（012-2）／話者（012-5）。

## 依存

- 前提: **DD-012-1**（ライブSTTが流れていること）。

## タスク一覧

### Phase 0: 事前精査
- [x] 📋 対象パス・🔬機械検証の精査（新規 `pipeline/refine.py`、`sidecar.py` に整形ワーカー、`lib.rs` relay/start_mic、`S05Realtime.vue`。検証=pytest＋headless sidecar＋実ウィンドウ）
- [x] 📐 実装前詳細化（外部I/F=契約 `refined`/`bypass` 追加／STTと整形の時間分離 → **下記「Phase 0 設計判断」**）
- [x] 😈 Devil's Advocate（下記 Phase 2 DA記録）

#### Phase 0 設計判断
- **整形は収音サイドカー内の別スレッドで回す（別プロセスにしない）**: 確定セグメントは `sidecar.py` の `_run_realtime` で発生するため、同プロセスのワーカースレッドが最短。Rust は relay に `refined`/`bypass` を足すだけ（新プロセス管理・新Stateなし）。
- **非ブロッキング＝小さな bounded queue（maxsize=3）＋バイパス**: STTループ(`sink`)は segment を即 emit し、整形は `put_nowait`。満杯なら捨てて `bypass:on` を emit（主役は絶対に止めない＝DoD）。空きが戻れば `bypass:off`。
- **契約**: `{"type":"refined","seq":N,"text":..}`（該当 seq 行へ後追い差し込み）／`{"type":"bypass","on":bool}`。stdout は JSON 専用（既存方針踏襲）。
- **ON/OFF は S-08 `use_llm_live` に連動**: Rust `start_mic` が ON のとき `--refine --live-model <live_model>` を付けて起動。表示の ON/OFF は S-05 の `showRefined` トグル（別軸）。
- **整形ロジックは純度高く分離**: `refine.py` に `build_refine_prompt`(純)・`refine_text`(Ollama, think=False＋`<think>`除去)。ワーカー（queue/thread/bypass）は sidecar 側。

### Phase 1: Python 側 — 追い上げ整形口 ✅
- [x] 📐 実装前詳細化（Phase 0 設計判断で確定）
- [x] 新規 `pipeline/refine.py`（`refine_text`/`build_refine_prompt`）＋ `sidecar.py` の `_run_realtime` に整形ワーカースレッド・bounded queue・bypass・停止時ドレインを追加。`--refine`/`--live-model` 引数
- [x] 🔬 機械検証: `pytest`（refine 3件追加・計 **70緑**）＋`ruff`緑。**headless 実走** `sidecar --simulate sample01.wav --refine`：segment 11 → **refined 5 / bypass 2 / error 0**（seq付き整形テキスト、速送りで bypass も作動＝非ブロッキング実証）
- [x] 😈 DA批判レビュー（下記）

### Phase 2: Rust 中継 ＋ S-05 結線 ✅
- [x] `lib.rs`: relay に `refined`→`stt-refined`／`bypass`→`stt-bypass`。`start_mic` は `use_llm_live` ON のとき `--refine --live-model` を付与（`live_refine_model` ヘルパ）
- [x] `S05Realtime.vue`: `AiSeg.seq` を保持し `stt-refined` を該当 seq 行の薄字 `refined` へ差し込み。`stt-bypass` を `bypass` バナーへ。既存 `showRefined` トグルで表示 ON/OFF
- [x] 🔬 機械検証（**実ウィンドウ**）: 実マイクで確定行の下に✨整形文が遅れて追従。**遅延0s・drop0・バイパス無し**で主役が止まらないことを確認（ログ: `refine=true`／segment→refined ペア／pause 後ドレイン1件）
- [x] 😈 DA批判レビュー（下記）

## 完了条件（DoD）

- ライブ中、確定行の下に整形文が遅れて追従表示され、ON/OFFが効く。
- 整形が詰まっても確定表示（主役）が遅延しない。

## ログ

### 2026-06-08
- DD作成（親 DD-012 の子）。基本設計の非ブロッキング追い上げ整形（qwen3:8b）を S-05 の既存スロットに結線する体験向上として起票。
- **Phase 0-2 実装＋検証 完了（実マイクで追い上げ表示を確認）**:
  - Python: 新規 `refine.py`（qwen3:8b 整形・think=False・`<think>`除去）＋ `sidecar.py` に非ブロッキング整形ワーカー（bounded queue maxsize=3／満杯で `bypass`／停止時ドレイン）。`--refine`/`--live-model` 追加。
  - Rust: relay に `refined`/`bypass`、`start_mic` を `use_llm_live` で `--refine` 起動（`live_refine_model`）。
  - Front: `S05Realtime.vue` で seq 突合して薄字 refined を差し込み、bypass バナー・`showRefined` トグルに結線。
  - 検証: `pytest` 70 / `ruff` / `vue-tsc` 緑、`tauri dev` 自動rebuild緑。headless（simulate）で refined5/bypass2、**実マイクで追従表示・遅延0s・バイパス無し**＝DoD達成。
  - 既知の割り切り: 整形品質は STT（base）と qwen 次第で粗い場合あり（追い上げ＝表示層。主役の確定文字は不変）。refined は表示のみで DB 未保存（`timeline_elements.text_refined` は null のまま＝別途）。
- **資源コントロール（ユーザー指摘反映）**: 録音中の整形は whisper と qwen を同時にCPUで回すため、非力環境向けに OFF 可能であることを明確化。**S-08「会議中のLLM整形を有効化」トグル OFF＝整形ワーカーを起動せず qwen を一切ロードしない（追加コスト0／whisper のみ）。** あわせて live ドロップダウンの「（無効）」/空/未設定 も OFF 扱いになるよう `live_refine_model` を修正（無効モデルで空振りさせない）。CPU配分は S-08 の Ollama num_thread でも絞れる。注意: 表示の `showRefined` は見た目のON/OFFのみ（計算は止めない）。資源を削るのは `use_llm_live` 側。
- **OFF制御の強化（ユーザー要望で3点・全実装）**:
  - ①**既定OFF化**: `schema.sql` の `use_llm_live` を DEFAULT 0／初期INSERT 0 に＋S-08フォーム既定 false＋db.rs テスト更新（`cargo test` **17緑**）。既存 dev DB の行も 0 へ反映し即時OFF（新規DBは既定OFFで生成）。
  - ②**会議ごとに切替（設定に潜らない）**: S-05 に「リアルタイム整形」トグル（`use_llm_live` で初期化・録音中は変更不可）を追加。`start_mic(refine: Option<bool>)` で今回ぶんを上書きでき、`live_refine_model` が override を優先（無指定時は設定値）。
  - ③**OFF時の「整形待ち」バッジを出さない**: mic meta に `refine` 実態を載せ、S-05 の `refineActive` で判定（整形が動いていない録音では unrefined バッジを出さない）。
  - 検証: `vue-tsc` / `pytest` 70 / `cargo test` 17 緑。

---

## DA批判レビュー記録

### Phase 2 DA批判レビュー

**DA観点:** 整形がSTTを食う／seq不一致での差し込み崩れ／バイパス境界。

| # | 発見した問題/改善点 | 重要度 | 再現手順 | DA観点 | 対応 |
|---|-------------------|--------|---------|--------|------|
| 1 | 整形が STT を食って確定表示が遅延 | 高 | 速い供給で整形が詰まる | STTを止めない | sink は `put_nowait` のみ＝STTループは整形を待たない。満杯は捨てて bypass。headless で segment が止まらず流れることを確認。済 |
| 2 | seq 不一致で別の行に差し込み | 中 | seq がズレる | 差し込み崩れ | refined は `segment` と同じ `ch.seq` を採番、フロントは seq 一致行にのみ差し込み。実機で行対応を確認。済 |
| 3 | バイパス ON/OFF のバタつき | 低 | 境界付近で詰まりが上下 | 表示のチラつき | 状態フラグで遷移時のみ emit（連続 on/off を出さない）。済 |
| 4 | 停止時に trailing refined を落とす | 低 | 停止直後に整形未完 | 取りこぼし | done 後にセンチネル＋join(timeout 20s) で掃き出し。実機で pause 後に refined 1件到達を確認。済 |
| 5 | qwen3 の思考トークンが混入 | 中 | think 出力 | 表示汚染 | `think=False`＋`<think>…</think>` 除去（test_refine で検証）。済 |
| 6 | 録音中の二重常駐（whisper＋qwen）でメモリ/CPU圧迫 | 中 | 長時間録音 | 資源 | base+qwen3:8b は実機内（実測 遅延0s）。終了時は summarize の switch_to_batch が qwen を退避（DD-012-2）。許容 |
