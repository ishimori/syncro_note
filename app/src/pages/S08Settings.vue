<script setup lang="ts">
// S-08 設定 — Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-08_settings.html。
// ローカル実行のチューニング（マイク／モデル／コア配分／データ保存）を反映。
// 「保存」は見た目のみ（永続化・Tauri/Node API への接続は別フェーズ）。
import { ref } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

const router = useRouter();

const leftDrawer = ref(true);

// マイク
const mics: string[] = ["既定 - マイク配列 (Realtek)", "USB会議マイク", "ヘッドセット"];
const mic = ref<string>("既定 - マイク配列 (Realtek)");

// モデル
const stts: string[] = ["whisper tiny", "whisper base", "whisper small"];
const stt = ref<string>("whisper base");
const lives: string[] = ["（無効）", "qwen3:8b", "gemma4:e4b"];
const live = ref<string>("qwen3:8b");
const batches: string[] = ["gemma4:26b", "Qwen3-30B-A3B"];
const batch = ref<string>("gemma4:26b");
const useLlmLive = ref<boolean>(true);
const kvOptions: string[] = ["f16", "q8_0"];
const kv = ref<string>("q8_0");

// スレッド / コア配分（8C/16T）
const nThreads = ref<number>(4);
const numThread = ref<number>(4);

// データ
const dbPath = ref<string>("%APPDATA%/SynchroniNote/data.sqlite");
const keepAudio = ref<boolean>(true);
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 戻る・保存 -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="arrow_back" @click="router.push('/s01')" />
        <q-toolbar-title>設定</q-toolbar-title>
        <q-btn unelevated no-caps color="green-6" icon="save" label="保存" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 760px; margin: 0 auto">
        <q-banner dense rounded class="bg-grey-2 q-mb-md text-grey-8">
          <template v-slot:avatar><q-icon name="tune" color="primary" /></template>
          ローカル実行のチューニング。コア配分は「合計が物理8コアを超えない」ことが目安（超過でスラッシング）。
        </q-banner>

        <!-- マイク -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="mic" class="q-mr-xs" />マイク
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <q-select outlined dense v-model="mic" :options="mics" label="既定の入力デバイス" />
          </q-card-section>
        </q-card>

        <!-- モデル -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="memory" class="q-mr-xs" />モデル
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-gutter-md">
            <q-select outlined dense v-model="stt" :options="stts" label="STT（文字起こし）" />
            <q-select outlined dense v-model="live" :options="lives" label="リアルタイム整形（live）" />
            <q-select outlined dense v-model="batch" :options="batches" label="終了後清書（batch）" />
            <q-toggle
              v-model="useLlmLive"
              label="会議中のLLM整形を有効化（任意の追い上げレイヤ）"
              color="primary"
            />
            <q-select
              outlined
              dense
              v-model="kv"
              :options="kvOptions"
              label="KVキャッシュ型（q8_0でメモリ半減）"
            />
          </q-card-section>
        </q-card>

        <!-- コア配分 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="developer_board" class="q-mr-xs" />スレッド / コア配分（8C/16T）
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-gutter-lg">
            <div>
              <div class="text-caption text-grey-7">whisper n_threads：{{ nThreads }}</div>
              <q-slider v-model="nThreads" :min="1" :max="8" markers label color="primary" />
            </div>
            <div>
              <div class="text-caption text-grey-7">Ollama num_thread：{{ numThread }}</div>
              <q-slider v-model="numThread" :min="1" :max="8" markers label color="primary" />
            </div>
            <q-banner dense class="bg-amber-1 text-grey-9" rounded>
              <q-icon name="warning" color="amber-8" /> 既定は STT↔LLM の時間分離（同時実行はメモリ帯域競合で16〜51%劣化しうる）。
            </q-banner>
          </q-card-section>
        </q-card>

        <!-- データ -->
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="folder" class="q-mr-xs" />データ
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-gutter-md">
            <q-input outlined dense v-model="dbPath" label="SQLite 保存先" readonly>
              <template v-slot:append><q-btn flat dense icon="folder_open" /></template>
            </q-input>
            <q-toggle
              v-model="keepAudio"
              label="音声を保存する（終了後の話者分離・再解析用）"
              color="primary"
            />
          </q-card-section>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
/* 画面固有のスタイル。テーマ変数（--q-primary/--q-secondary）は
   アプリ全体で設定済みのため、ここでは個別指定しない。 */
</style>
