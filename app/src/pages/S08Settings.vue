<script setup lang="ts">
// S-08 設定 — Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-08_settings.html。
// ローカル実行のチューニング（マイク／モデル／コア配分／データ保存）を反映。
// 「保存」は見た目のみ（永続化・Tauri/Node API への接続は別フェーズ）。
import { ref, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

// app_settings（Rust/serde の snake_case）と 1:1（DD-012-7）
interface AppSettings {
  mic_device: string | null;
  stt_model: string | null;
  live_model: string | null;
  batch_model: string | null;
  use_llm_live: boolean;
  kv_cache_type: string | null;
  whisper_n_threads: number | null;
  ollama_num_thread: number | null;
  db_path: string | null;
  keep_audio: boolean;
  updated_at: string;
}
// 素ブラウザ(Playwright)には Tauri ランタイムが無い → 保存/読込をスキップ。
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const router = useRouter();

const leftDrawer = ref(true);

// マイク
const mics: string[] = ["既定 - マイク配列 (Realtek)", "USB会議マイク", "ヘッドセット"];
const mic = ref<string>("既定 - マイク配列 (Realtek)");

// モデル
// STT も同じ { value, label, caption } 方式。基準は速度↔日本語精度のトレードオフ
// （根拠: DD-003 実測 日本語CER medium 0.26 ≪ base 0.54 ≪ tiny 0.82 / base が即時表示の推奨）。
// ※ small は本プロジェクト未計測のため数値は出さず定性表現にとどめる。
const stts = [
  { value: "whisper tiny", label: "whisper tiny", caption: "最速・最軽量。ただし日本語の精度は最低（動作確認や速度優先のとき）" },
  { value: "whisper base", label: "whisper base", caption: "推奨。速度と精度のバランスが良く、即時表示向き" },
  { value: "whisper small", label: "whisper small", caption: "精度重視。baseより重いが聞き取りに強い" },
];
const stt = ref<string>("whisper base");
// 選択肢は { value=モデルタグ, label=表示名, caption=選び方メモ }。
// caption はドロップダウン内にだけ薄字で出す選定基準（根拠: 基本設計書 §4.1 モデル選定表）。
// emit-value+map-options により v-model にはタグ文字列だけが入る（将来 Ollama にそのまま渡せる）。
const lives = [
  { value: "（無効）", label: "（無効）", caption: "LLM整形なし。文字起こしそのまま＋辞書でケバ取り（最も軽い）" },
  { value: "qwen3:8b", label: "qwen3:8b", caption: "推奨・反応最速。日本語の固有名詞や専門用語の補正に強い" },
  { value: "gemma4:e4b", label: "gemma4:e4b", caption: "速度に余裕。8bが重くて追いつかない時の予備（フォールバック）" },
];
const live = ref<string>("qwen3:8b");
const batches = [
  { value: "gemma4:26b", label: "gemma4:26b", caption: "推奨・本命。26B級の品質を4B級の速さで（MoE活性4B）" },
  { value: "Qwen3-30B-A3B", label: "Qwen3-30B-A3B", caption: "比較用の候補。やや大きめでメモリも多めに要る" },
];
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

// 永続化（DD-012-7）: 起動時に app_settings をロード、「保存」でDBへ書く。
const saving = ref(false);
const savedMsg = ref("");

onMounted(async () => {
  if (!isTauri) return;
  try {
    const s = await invoke<AppSettings>("get_settings");
    if (s.mic_device) mic.value = s.mic_device;
    if (s.stt_model) stt.value = s.stt_model;
    if (s.live_model) live.value = s.live_model;
    if (s.batch_model) batch.value = s.batch_model;
    useLlmLive.value = s.use_llm_live;
    if (s.kv_cache_type) kv.value = s.kv_cache_type;
    if (s.whisper_n_threads != null) nThreads.value = s.whisper_n_threads;
    if (s.ollama_num_thread != null) numThread.value = s.ollama_num_thread;
    if (s.db_path) dbPath.value = s.db_path;
    keepAudio.value = s.keep_audio;
  } catch (e) {
    savedMsg.value = "読み込み失敗: " + String(e);
  }
});

const save = async (): Promise<void> => {
  if (!isTauri) return;
  saving.value = true;
  savedMsg.value = "";
  try {
    const settings: AppSettings = {
      mic_device: mic.value,
      stt_model: stt.value,
      live_model: live.value,
      batch_model: batch.value,
      use_llm_live: useLlmLive.value,
      kv_cache_type: kv.value,
      whisper_n_threads: nThreads.value,
      ollama_num_thread: numThread.value,
      db_path: dbPath.value || null,
      keep_audio: keepAudio.value,
      updated_at: new Date().toISOString(),
    };
    await invoke("save_settings", { settings });
    savedMsg.value = "保存しました（次回の録音から反映）";
  } catch (e) {
    savedMsg.value = "保存に失敗: " + String(e);
  } finally {
    saving.value = false;
  }
};
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
        <q-chip v-if="savedMsg" dense color="white" text-color="primary" class="q-mr-sm">
          {{ savedMsg }}
        </q-chip>
        <q-btn
          unelevated
          no-caps
          color="green-6"
          icon="save"
          label="保存"
          :loading="saving"
          :disable="!isTauri"
          @click="save"
        />
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
            <q-select
              outlined
              dense
              v-model="stt"
              :options="stts"
              emit-value
              map-options
              label="STT（文字起こし）"
            >
              <template v-slot:option="{ itemProps, opt }">
                <q-item v-bind="itemProps">
                  <q-item-section>
                    <q-item-label>{{ opt.label }}</q-item-label>
                    <q-item-label caption>{{ opt.caption }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              outlined
              dense
              v-model="live"
              :options="lives"
              emit-value
              map-options
              label="リアルタイム整形（live）"
            >
              <template v-slot:option="{ itemProps, opt }">
                <q-item v-bind="itemProps">
                  <q-item-section>
                    <q-item-label>{{ opt.label }}</q-item-label>
                    <q-item-label caption>{{ opt.caption }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
            <q-select
              outlined
              dense
              v-model="batch"
              :options="batches"
              emit-value
              map-options
              label="終了後清書（batch）"
            >
              <template v-slot:option="{ itemProps, opt }">
                <q-item v-bind="itemProps">
                  <q-item-section>
                    <q-item-label>{{ opt.label }}</q-item-label>
                    <q-item-label caption>{{ opt.caption }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
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
