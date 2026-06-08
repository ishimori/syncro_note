<script setup lang="ts">
// S-06 議事録生成中（バッチ清書）— DD-012-2 Phase 2: 実データ結線。
// 「会議を終了」で渡された確定テキスト(minutesSession)を Rust 経由で清書サイドカー(gemma)へ投げ、
// summary-* イベント（モデル切替→生成）を listen して進捗・ストリームを表示する。
//   契約: summary-meta / summary-status / summary-progress / summary-done / summary-error
// 注意: invoke/listen は実ウィンドウ(Tauri)専用。素ブラウザ(Playwright)では起動できない。
import { ref, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import AppNav from "../components/AppNav.vue";
import { minutesSession, resetMinutesSession } from "../session";

const router = useRouter();
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const leftDrawer = ref(true);

// 進捗ステッパ（1:退避 / 2:ロード / 3:清書）。summary-status と最初の progress で進める。
const step = ref(1);
const statusText = ref("準備中…");
const chars = ref(0); // 生成済み文字数（ストリーミング中の目安）
const outTokens = ref(0);
const tps = ref(0);
const evalS = ref(0);
const preview = ref("");
const done = ref(false);
const errorMsg = ref("");
const noInput = ref(false); // 直接遷移などで清書元が無い

let acc = ""; // progress の delta を連結
const unlisteners: UnlistenFn[] = [];

// literal な "\n"（バックスラッシュ+n）をストリーミング表示でも改行に見せる
// （保存値は Python 側 normalize_minutes で正規化済み。ここは表示の見栄えのみ）。
const softNl = (s: string): string => s.replace(/\\r\\n/g, "\n").replace(/\\n/g, "\n");

onMounted(async () => {
  if (!isTauri) {
    statusText.value = "実ウィンドウ専用";
    errorMsg.value = "この画面は実ウィンドウ（Tauri）でのみ動作します。";
    return;
  }
  if (!minutesSession.transcript) {
    noInput.value = true;
    return;
  }
  unlisteners.push(
    await listen<{ model: string }>("summary-meta", (e) => {
      minutesSession.batchModel = e.payload.model;
      step.value = 1;
      statusText.value = "モデルを準備中…";
    }),
    await listen<{ stage: string }>("summary-status", (e) => {
      const stage = e.payload.stage;
      if (stage === "unloading") {
        step.value = 1;
        statusText.value = "リアルタイム用モデルを退避中…";
      } else if (stage === "unload_timeout") {
        statusText.value = "退避に時間がかかっています…";
      } else if (stage === "loading_batch") {
        step.value = 2;
        statusText.value = "清書モデルを読込中…";
      }
    }),
    await listen<{ delta: string; chars: number }>("summary-progress", (e) => {
      if (step.value < 3) {
        step.value = 3;
        statusText.value = "全文脈を統合して清書中…";
      }
      acc += e.payload.delta;
      preview.value = softNl(acc);
      chars.value = e.payload.chars;
    }),
    await listen<{ markdown: string; output_tokens: number; eval_s: number }>("summary-done", (e) => {
      preview.value = e.payload.markdown; // Python で正規化済み
      outTokens.value = e.payload.output_tokens;
      evalS.value = e.payload.eval_s;
      tps.value =
        e.payload.eval_s > 0 ? Math.round((e.payload.output_tokens / e.payload.eval_s) * 10) / 10 : 0;
      minutesSession.finalMarkdown = e.payload.markdown;
      minutesSession.generationSeconds = Math.round(e.payload.eval_s);
      done.value = true;
      statusText.value = "清書が完了しました";
    }),
    await listen<{ message: string }>("summary-error", (e) => {
      errorMsg.value = e.payload.message;
    }),
  );

  try {
    await invoke("start_summarize", {
      transcript: minutesSession.transcript,
      title: minutesSession.title,
    });
  } catch (e) {
    errorMsg.value = String(e);
  }
});

onUnmounted(() => {
  unlisteners.forEach((u) => u());
  // 完了(done)前に画面を離れたら清書サイドカーを止め、清書セッションを破棄する
  // （会議はまだDBに作っていないので「生成中」の幽霊は残らない）。完了後は S-07 の保存に委ねる。
  if (!done.value) {
    if (isTauri) invoke("abort_summarize").catch(() => {});
    resetMinutesSession();
  }
});

const openPreview = (): void => {
  router.push("/s07");
};

// 中断: 実行中サイドカーを kill して S-05 へ戻る。
const abort = async (): Promise<void> => {
  if (isTauri) {
    try {
      await invoke("abort_summarize");
    } catch {
      /* 失敗は無視（ウィンドウ破棄でも kill される） */
    }
  }
  router.push("/s05");
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 生成中スピナー / 完了 / エラー -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-spinner-gears v-if="!done && !errorMsg" size="24px" class="q-mr-sm" />
        <q-icon v-else-if="done" name="check_circle" size="24px" class="q-mr-sm" />
        <q-icon v-else name="error" size="24px" class="q-mr-sm" />
        <q-toolbar-title>
          {{ done ? "清書が完了しました" : errorMsg ? "清書に失敗しました" : "議事録を生成中…" }}
        </q-toolbar-title>
        <q-badge v-if="done" color="green-5" label="completed へ" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 860px; margin: 0 auto">
        <!-- 清書元が無い（直接遷移など） -->
        <q-banner v-if="noInput" rounded class="bg-amber-2 text-grey-9">
          <template v-slot:avatar><q-icon name="info" color="amber-8" /></template>
          清書する文字起こしがありません。S-05 で録音・文字起こしをしてから「会議を終了」してください。
          <template v-slot:action>
            <q-btn flat no-caps color="primary" label="リアルタイム画面へ" @click="router.push('/s05')" />
          </template>
        </q-banner>

        <template v-else>
          <q-banner rounded class="bg-grey-2 q-mb-md text-grey-9">
            <template v-slot:avatar><q-icon name="psychology" color="primary" size="28px" /></template>
            ローカルCPUで全文脈を分析して清書しています。<b>目安 3〜6分</b>。完全オフラインで処理中。
          </q-banner>

          <!-- エラー -->
          <q-banner v-if="errorMsg" rounded class="bg-red-2 q-mb-md text-red-10">
            <template v-slot:avatar><q-icon name="error" color="red-7" /></template>
            清書中にエラーが発生しました: {{ errorMsg }}
            <template v-slot:action>
              <q-btn flat no-caps color="red-8" label="戻る" @click="router.push('/s05')" />
            </template>
          </q-banner>

          <!-- モデル切替ステッパ -->
          <q-card flat bordered class="q-mb-md">
            <q-card-section>
              <div class="text-subtitle1 text-weight-medium">
                <q-icon name="swap_horiz" class="q-mr-xs" />処理フェーズ
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section>
              <q-stepper v-model="step" vertical flat color="primary" animated>
                <q-step
                  :name="1"
                  title="軽量モデルの退避"
                  icon="logout"
                  :done="step > 1"
                  caption="qwen を keep_alive:0 で退避・/api/ps 空確認"
                >
                  二重常駐によるメモリ圧迫を避けるため、リアルタイム用モデルを完全アンロード。
                </q-step>
                <q-step
                  :name="2"
                  title="清書モデルのロード"
                  icon="download"
                  :done="step > 2"
                  caption="gemma を展開"
                >
                  メモリの大部分を清書モデルのコンテキストへ割り当て。
                </q-step>
                <q-step
                  :name="3"
                  title="全文脈を統合して清書"
                  icon="auto_awesome"
                  caption="確定テキスト＋人間メモ(最優先)"
                >
                  確定文字起こしと人間メモを統合し、議事録Markdownを生成。
                </q-step>
              </q-stepper>
            </q-card-section>
          </q-card>

          <!-- 進捗 -->
          <q-card flat bordered class="q-mb-md">
            <q-card-section>
              <div class="row items-center q-mb-xs">
                <div class="text-caption text-grey-7">{{ statusText }}</div>
                <q-space />
                <div v-if="done" class="text-caption text-grey-7">
                  {{ outTokens }} tok ・ {{ tps }} tok/s ・ {{ evalS.toFixed(1) }}s
                </div>
                <div v-else class="text-caption text-grey-7">{{ chars }} 文字</div>
              </div>
              <q-linear-progress v-if="done" :value="1" color="green" rounded size="10px" />
              <q-linear-progress v-else indeterminate color="primary" rounded size="10px" />
            </q-card-section>
          </q-card>

          <!-- ストリーミングプレビュー -->
          <div class="text-caption text-grey-7 q-mb-xs">プレビュー（ストリーミング）</div>
          <div class="preview q-pa-md">{{ preview }}<span v-if="!done && !errorMsg">▋</span></div>

          <div class="row justify-end q-mt-md q-mb-xl q-gutter-sm">
            <q-btn v-if="!done" flat no-caps color="grey-7" icon="close" label="中断" @click="abort" />
            <q-btn
              v-else
              unelevated
              no-caps
              color="primary"
              icon="check"
              label="プレビューを開く"
              @click="openPreview"
            />
          </div>
        </template>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.preview {
  background: #0f172a;
  color: #e2e8f0;
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
  border-radius: 8px;
  min-height: 220px;
  white-space: pre-wrap;
}
</style>
