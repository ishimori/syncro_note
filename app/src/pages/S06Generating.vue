<script setup lang="ts">
// S-06 議事録生成中（バッチ）— Phase 2: 静的骨格（見た目＋ローカル動作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-06_generating.html。
// 「軽量モデル退避→特大モデルロード→全文脈を統合して清書」のモデル切替フェーズと、
// ストリーミングプレビュー（トークン進捗）を再現。実際のOllama接続は Phase 3 で行う。
import { ref, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

const router = useRouter();

const leftDrawer = ref(true);

// モデル切替ステッパ（1:退避 / 2:ロード / 3:清書）
const step = ref<number>(1);
const tok = ref<number>(0);
const tps = ref<number>(12.6);
const preview = ref<string>("");
const done = ref<boolean>(false);

// 清書結果（ストリーミングで少しずつ表示するダミー）
const full: string =
  "## ■ 会議概要\n基本設計レビューを実施。確定テキスト即表示を主役とする方針を確認。\n\n## ■ 決定事項\n- 佐藤：話者分離PoC（pyannote/sherpa-onnx）を6/20までに\n- 鈴木：清書モデルを gemma4:26b に確定\n\n## ■ アクションアイテム\n- [ ] DD-004 起票（佐藤）\n";

// setTimeout / setInterval のハンドルを保持し、onUnmounted で確実に後始末する。
let stepTimer2: ReturnType<typeof setTimeout> | null = null;
let stepTimer3: ReturnType<typeof setTimeout> | null = null;
let streamTimer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  stepTimer2 = setTimeout(() => {
    step.value = 2;
  }, 900);
  stepTimer3 = setTimeout(() => {
    step.value = 3;
  }, 1900);
  let i = 0;
  streamTimer = setInterval(() => {
    if (step.value < 3) return;
    preview.value = full.slice(0, i);
    tok.value = Math.min(3000, 50 + i * 9);
    i += 2;
    if (i > full.length) {
      if (streamTimer !== null) clearInterval(streamTimer);
      streamTimer = null;
      done.value = true;
      tok.value = 3000;
    }
  }, 40);
});

onUnmounted(() => {
  if (stepTimer2 !== null) clearTimeout(stepTimer2);
  if (stepTimer3 !== null) clearTimeout(stepTimer3);
  if (streamTimer !== null) clearInterval(streamTimer);
});
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 生成中スピナー＋ステータス -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-spinner-gears size="24px" class="q-mr-sm" />
        <q-toolbar-title>議事録を生成中…</q-toolbar-title>
        <q-badge color="amber-8" label="completed へ移行中" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 860px; margin: 0 auto">
        <q-banner rounded class="bg-grey-2 q-mb-md text-grey-9">
          <template v-slot:avatar><q-icon name="psychology" color="primary" size="28px" /></template>
          ローカルCPUで全文脈を深く分析しています。<b>目安 3〜6分</b>（特大モデルの活性4B級・出力2000〜4000tok）。完全オフラインで処理中。
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
                caption="qwen3:8b に keep_alive:0 / /api/ps 空確認"
              >
                二重常駐によるOOMを避けるため、リアルタイム用モデルを完全アンロード。
              </q-step>
              <q-step
                :name="2"
                title="特大モデルのロード"
                icon="download"
                :done="step > 2"
                caption="gemma4:26b（MoE活性4B）を展開"
              >
                メモリの大部分を清書モデルのコンテキストへ割り当て。
              </q-step>
              <q-step
                :name="3"
                title="全文脈を統合して清書"
                icon="auto_awesome"
                caption="基本情報＋資料＋人間メモ(最優先)＋確定タイムライン"
              >
                map-reduce で長文に対応。人間メモは要約段で切り捨てない。
              </q-step>
            </q-stepper>
          </q-card-section>
        </q-card>

        <!-- 進捗 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="row items-center q-mb-xs">
              <div class="text-caption text-grey-7">生成トークン {{ tok }} / ~3000</div>
              <q-space />
              <div class="text-caption text-grey-7">{{ tps }} tok/s</div>
            </div>
            <q-linear-progress :value="tok / 3000" color="primary" track-color="grey-3" rounded size="10px" />
          </q-card-section>
        </q-card>

        <!-- ストリーミングプレビュー -->
        <div class="text-caption text-grey-7 q-mb-xs">プレビュー（ストリーミング）</div>
        <div class="preview q-pa-md">{{ preview }}<span v-if="!done">▋</span></div>

        <div class="row justify-end q-mt-md">
          <q-btn v-if="!done" flat no-caps color="grey-7" icon="close" label="中断" />
          <q-btn
            v-else
            unelevated
            no-caps
            color="primary"
            icon="check"
            label="プレビューを開く"
            @click="router.push('/s07')"
          />
        </div>
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
