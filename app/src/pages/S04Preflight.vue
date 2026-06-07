<script setup lang="ts">
// S-04 会議開始の準備（プリフライト）— Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-04_preflight.html。
// 無音録音・モデル未ロードの事故を防ぐ「開始前チェック」を反映。
// 実マイク取得・モデルロード（Python/Tauri）との接続は Phase 3 で行う。
import { ref, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

const router = useRouter();

const leftDrawer = ref(true);

const mics: string[] = ["既定 - マイク配列 (Realtek)", "USB会議マイク", "ヘッドセット"];
const mic = ref<string>(mics[0]);
const useLlm = ref(true);

// 入力レベルメーター（見た目のみのダミーアニメーション）。Phase 3 で実音声に差し替え。
const level = ref(20);
let levelTimer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  levelTimer = setInterval(() => {
    level.value = 15 + Math.round(Math.random() * 70);
  }, 400);
});
onUnmounted(() => {
  if (levelTimer !== undefined) clearInterval(levelTimer);
});
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 戻る・タイトル・録音前バッジ -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="arrow_back" @click="router.push('/s01')" />
        <q-toolbar-title>会議開始の準備（プリフライト）</q-toolbar-title>
        <q-badge color="red-5" label="● 録音前" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 720px; margin: 0 auto">
        <q-banner dense rounded class="bg-grey-2 q-mb-md text-grey-8">
          <template v-slot:avatar><q-icon name="checklist" color="primary" /></template>
          無音録音・モデル未ロードの事故を防ぐため、開始前に確認します。
        </q-banner>

        <!-- 会議サマリ -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">設計レビュー</div>
            <div class="text-grey-7">参加者: 鈴木（PM）・佐藤（エンジニア）／用語: Qwen, Tauri, SQLite</div>
          </q-card-section>
        </q-card>

        <!-- マイク -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium"><q-icon name="mic" class="q-mr-xs" />マイク</div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-gutter-md">
            <q-select outlined v-model="mic" :options="mics" label="入力デバイス" dense />
            <div>
              <div class="text-caption text-grey-7 q-mb-xs">入力レベル（話してみてバーが動けばOK）</div>
              <div class="meter"><div :style="{ width: level + '%' }" /></div>
            </div>
            <q-item dense class="q-pa-none">
              <q-item-section avatar><q-icon name="check_circle" color="green-6" /></q-item-section>
              <q-item-section>16kHz / モノラル / f32 で取得可能</q-item-section>
            </q-item>
          </q-card-section>
        </q-card>

        <!-- モデル -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="memory" class="q-mr-xs" />モデルのロード状態
            </div>
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item>
              <q-item-section avatar><q-icon name="record_voice_over" color="primary" /></q-item-section>
              <q-item-section>
                <q-item-label>文字起こし（STT）</q-item-label>
                <q-item-label caption>whisper base（CPU, n_threads=4）</q-item-label>
              </q-item-section>
              <q-item-section side><q-badge color="green-6" label="ロード済" /></q-item-section>
            </q-item>
            <q-item>
              <q-item-section avatar><q-icon name="auto_fix_high" color="primary" /></q-item-section>
              <q-item-section>
                <q-item-label>リアルタイム整形（任意）</q-item-label>
                <q-item-label caption>qwen3:8b（追い上げレイヤ）</q-item-label>
              </q-item-section>
              <q-item-section side><q-toggle v-model="useLlm" color="primary" /></q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <div class="row q-gutter-sm justify-end">
          <q-btn flat no-caps label="戻る" @click="router.push('/s01')" />
          <q-btn
            unelevated
            no-caps
            color="red-6"
            icon="fiber_manual_record"
            label="録音開始"
            @click="router.push('/s05')"
          />
        </div>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.meter {
  height: 14px;
  border-radius: 7px;
  background: #e5e7eb;
  overflow: hidden;
}
.meter > div {
  height: 100%;
  background: linear-gradient(90deg, #22c55e, #eab308, #ef4444);
}
</style>
