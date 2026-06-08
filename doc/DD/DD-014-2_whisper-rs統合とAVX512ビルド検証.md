# DD-014-2: whisper-rs STT 統合と AVX-512 ビルド検証

| 作成日 | 更新日 | ステータス |
|--------|--------|------------|
| 2026-06-08 | 2026-06-08 | 進行中（Phase1 AVX-512=GO / Phase2予備計測=素のMSVCビルドは基準比 約8倍遅く要ツールチェーン対策〔clang-cl/BLAS/版固定〕 / 本実装は DD-014-1 後） |

> 親: [DD-014（P4-3 ホットパス Rust 移植）](DD-014_P4-3ホットパスRust移植_cpal_whisper-rs_Tokio.md) ／ アプローチ: 標準（実機ベンチ）
> 依存: [DD-014-1](DD-014-1_cpal収音とringbufとVADチャンク化.md)

## 目的

whisper-rs（whisper.cpp binding）を統合し、**n_threads=4・AVX-512 有効化を確認**したうえで、VAD チャンクを STT にかけて Python 版（DD-010）と RTF/遅延を比較する。

## 背景・課題

- AVX-512 が有効化されないとチューニング効果が0で性能目標未達（親DDの起票時DA#1）。`cargo --release`/RUSTFLAGS の設定と `objdump -d | grep -i avx512` での検証が要。**着手前倒し（early action）**で先にビルド検証する。
- STT/LLM 時間分離既定（基本設計書 §1 原則6）。whisper threads ≤ 4。

## 検討内容

**スコープイン**
- whisper-rs 統合・n_threads=4 設定
- AVX-512 有効化確認（`objdump -d | grep avx512`。early action）
- spawn_blocking による CPUバウンド（whisper-rs）の専用 pool 化
- DD-010（Python: RTF≈0.527 / E2E≈4s）との RTF/E2E 遅延比較ログ

**スコープアウト（重複回避）**
- cpal収音・VAD → DD-014-1
- Ollama LLM 連携 → DD-014-3
- DB 書込み → DD-012-3 の Rust単独所有原則に従い T_state へ集約（DD-014-4）
- 話者埋め込み ONNX 本体 → DD-004-1（別セッション）

## 決定事項

- ビルドが AVX-512 を含むことを `objdump` で機械確認してから性能評価に進む。

## タスク一覧

### Phase 0: 事前精査
- [ ] 📋 対象ファイル明記（whisper-rs 依存・STT モジュール・ビルド設定）
- [ ] 📐 実装前詳細化トリガー判定（新規依存＋性能特性 → **詳細化要**）
- [ ] 😈 Devil's Advocate（AVX-512未有効・Windows binding の不完全さ）

### Phase 1: AVX-512 ビルド検証（前倒し）— ✅ 完了 2026-06-08（判定: GO）
- [x] whisper.cpp（vendored: `whisper-rs-sys 0.15.0` 同梱）を MSVC 14.50 + Ninja で release ビルドし SIMD 有効化を確認
  - configure: `GGML_NATIVE=ON` が `HAS_AVX512_1 - Success` を検出 → `Adding CPU backend variant ggml-cpu: /arch:AVX512 GGML_AVX512`
- [x] 🔬 機械検証: `dumpbin /disasm` で AVX-512 命令の実在を確認（ggml-cpu.dll = 712KB）
  - `zmm` レジスタ 4820 件 / マスク `{k0-7}` 104 件 / AVX-512専用 mnemonic 148 件
  - 実例: `vcvttps2dq zmm1,zmmword ptr[...]` / `vmovdqu32 zmmword ptr[...],zmm1` / `vpmovzxwd zmm0,...`
- 補足: whisper-rs の **Rustクレート本体**ビルドは `bindgen` が **libclang.dll を要求**し、LLVM未導入のため失敗。AVX-512検証はFFIに非依存なため vendored C++ を直接ビルドして確定した。実装本番（DD-014-1/2）では **LLVM/libclang の導入が前提**（`winget install LLVM.LLVM` 等・約2.5GB）。

### Phase 2: STT 統合＋RTF比較
- [ ] 📐 実装前詳細化 → 👀 ユーザーレビュー
- [ ] VADチャンクを whisper-rs で文字起こし、spawn_blocking pool 化
- [ ] 🔬 機械検証: RTF が DD-010 比 15%以上改善の見込みを実測ログで確認
- [ ] 😈 DA批判レビュー（最低1件）

## ログ

### 2026-06-08
- 起票（DD-014 の子・未実装）。
- **early action（AVX-512検証）完了 → 判定 GO**。隔離スパイク `C:\tmp\whisper-avx512-spike`（本体 `app/src-tauri` を汚さず別 target）で実施。
  - ① `whisper-rs = 0.16` の Rust ビルドを試行 → `whisper-rs-sys 0.15` の build script が `bindgen` で **libclang 未検出により失敗**（LLVM未導入）。
  - ② AVX-512 は FFI と無関係なので方針転換し、cargo が展開した **vendored whisper.cpp（ggml 0.9.5）を cmake(Ninja) + MSVC 14.50 で直接 release ビルド**。
  - ③ configure で `GGML_NATIVE` が AVX-512 を自動検出し `/arch:AVX512 GGML_AVX512` を有効化、28/28 完走。
  - ④ `dumpbin /disasm` で ggml-cpu.dll に AVX-512 命令を機械確認（`zmm` 4820 / `{k}` 104 / AVX-512専用 148）。
  - ⇒ 親 起票時DA#1（「AVX-512未有効ならチューニング効果0」）のリスクを**実証で解消**。性能改善の前提が実機（Ryzen 7 PRO 8840HS / Zen4）で成立。明示 `-DGGML_AVX512=ON` フォールバックは不要だった。
- 既知の前提（申し送り）: 実装本番で whisper-rs(Rust) を組むには **LLVM/libclang のインストールが必須**。配布(DD-012-6)の単一バイナリ化前提とも干渉しうるため要検討。
- **Phase2 予備計測で重大所見（RTFギャップ）→ 素の whisper-rs は Python基準比 約8倍遅い**。LLVM/libclang を pip ホイールで導入し whisper-rs(0.16, openmp) を実ビルドして実音声計測:
  - 条件: 同一 `ggml-medium.bin`（DD-005キャッシュ再利用）/ `sample01.wav`(70s) / threads=8 / batch。文字起こし精度は正確（日本語良好）。
  - **whisper-rs medium = RTF 3.5**。基準を実機で再現 → **pywhispercpp medium = RTF 0.42**（DD-005の0.386と一致・再現OK）。⇒ 約8倍遅い。
  - 切り分け（潰した仮説）: ①AVX-512未有効=✗（ggml-cpu.lib に zmm 10845・runtime適用済）/ ②スレッド不足=✗（threads 1→8 で RTF 38→3.5、約10倍スケール）/ ③OpenMP=✗（feature有効化＝`GGML_OPENMP=ON`確認でも不変）/ ④SIMDフラグ明示=✗（`GGML_NATIVE=OFF`＋`GGML_AVX512/AVX2/FMA/F16C=ON`で強制クリーン再ビルドしても RTF不変）。
  - 物証: 同一mediumで **compute buffer(encode) が pywhispercpp 44.6MB vs whisper-rs 170.2MB**（約3.8倍）。⇒ フラグでなく **whisper.cpp/ggml のバージョン差・ビルド品質（MSVCコード生成）** が主因の線が濃厚。
  - **結論**: DD-014 の性能DoDは「whisper-rs を入れるだけ」では未達。実装本番で **clang-cl ビルド or OpenBLAS or whisper.cpp版固定** の検証が必須。これは **DD-005 起票時DA#1（「製品ビルド(whisper-rs, AVX-512有効)で実RTFを再測せよ」）への回答**＝再測したら素のMSVCビルドは基準に届かない、を実証した。
  - 次の一手候補（未実施）: LLVM(約2.5GB)導入→ `CMAKE_C_COMPILER/CMAKE_CXX_COMPILER=clang-cl` で whisper-rs-sys を clang ビルドして再測。/ もしくは `openblas` feature。
  - スパイク資産: `C:\tmp\whisper-avx512-spike`（隔離・本体未汚染）。bench.log/bench2.log/bench4.log・disasm.txt 等にエビデンス。

---

## DA批判レビュー記録

<!-- DA批判レビューの手順・品質フィルター・再チェック条件は doc/da-method.md を参照 -->

### Phase 1 DA（早期検証で先出しリスクを実証解消）
- 親 起票時DA#1「AVX-512が有効化されないとチューニング効果0で性能目標未達」→ **解消**。`GGML_NATIVE` が本実機(Zen4)+MSVC で AVX-512 を自動有効化し、dumpbin で zmm 命令 4820 件を確認。
- 新規DA（Phase2 へ申し送り）: whisper-rs(Rust) は libclang 必須。CI/配布環境での LLVM 依存が DD-012-6（配布・単一バイナリ化）と干渉しうる。DD-014 親「スコープ外/未決事項」に追記検討。

### Phase N DA批判レビュー
（着手時に記録）
