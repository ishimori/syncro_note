<script setup lang="ts">
// S-04 会議開始の準備（プリフライト）。DD-012-8 で実データ化。
// 正＝設計SSOT doc/spec/画面設計書.md §S-04（入力レベル・無音時は録音開始を抑止・既定は app_settings）。
// 入力レベルは軽量サイドカー(--level)の実測RMSを stt-level イベントで受ける。実マイク確認は実ウィンドウ。
import { ref, onMounted, onUnmounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useRouter, useRoute } from "vue-router";
import AppNav from "../components/AppNav.vue";
import { getMeetingDetail } from "../api";

// app_settings の必要フィールド（DD-012-7）
interface AppSettings {
  mic_device: string | null;
  stt_model: string | null;
  whisper_n_threads: number | null;
  live_model: string | null;
  use_llm_live: boolean;
}
interface LevelEvent {
  rms: number;
}

const router = useRouter();
const route = useRoute();
// 予定(scheduled)から開始したときの会議id。録音→清書まで持ち回り、事前資料を清書に統合する（DD-012-10）。
const linkedId = typeof route.query.id === "string" ? route.query.id : "";
const leftDrawer = ref(true);
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

// 会議サマリ（Bug#5/DD-012-12）: 予定(?id=)の実データを表示。固定文言を排す。ad-hoc 録音では既定文。
const meetingTitle = ref("その場で録音");
const meetingParticipants = ref<string[]>([]);
const meetingAgenda = ref("");
const meetingVocab = ref<string[]>([]); // 専門用語（DD-012-12 Bug#7・実データ）

// マイク（実デバイス列挙は別DD。当面は設定の既定 or 固定候補）
const mics: string[] = ["既定 - マイク配列 (Realtek)", "USB会議マイク", "ヘッドセット"];
const mic = ref<string>(mics[0]);
const useLlm = ref(true);

// モデル表示（S-08 設定の実値を反映）
const sttModel = ref("whisper base");
const sttThreads = ref(4);
const liveModel = ref("qwen3:8b");

// 入力レベル（実測 RMS → 0-100 表示）と無音ガード
const level = ref(0);
const detected = ref(false); // 直近に入力ありか（メータ脇のライブ表示用）
const everDetected = ref(false); // 一度でも入力を検出したか（録音開始の解放条件・無音で戻さない）
const SILENCE_RMS = 0.015; // これ未満は無音扱い（暗騒音を弾く小さめ閾値・つまみ）
let lastVoiceAt = 0;

const unlisteners: UnlistenFn[] = [];

onMounted(async () => {
  if (!isTauri) return;
  // 予定から来た場合(?id=)は会議サマリを実データで満たす（Bug#5: 固定文言の排除）。
  if (linkedId) {
    try {
      const d = await getMeetingDetail(linkedId);
      if (d) {
        meetingTitle.value = d.meeting.title;
        meetingParticipants.value = d.participants.map((p) =>
          p.role ? `${p.name}（${p.role}）` : p.name,
        );
        meetingAgenda.value = d.meeting.agenda ?? "";
        meetingVocab.value = d.vocab ?? [];
      }
    } catch {
      /* 取得失敗時は既定表示のまま */
    }
  }
  // 既定を app_settings から反映
  try {
    const s = await invoke<AppSettings>("get_settings");
    if (s.mic_device) mic.value = s.mic_device;
    if (s.stt_model) sttModel.value = s.stt_model;
    if (s.whisper_n_threads != null) sttThreads.value = s.whisper_n_threads;
    if (s.live_model) liveModel.value = s.live_model;
    useLlm.value = s.use_llm_live;
  } catch {
    /* 読めなければ既定表示のまま */
  }
  // 入力レベル購読 → メータ＋無音ガード
  unlisteners.push(
    await listen<LevelEvent>("stt-level", (e) => {
      const rms = e.payload.rms;
      level.value = Math.min(100, Math.round(rms * 800));
      if (rms >= SILENCE_RMS) {
        lastVoiceAt = Date.now();
        everDetected.value = true; // 一度検出したら以後は録音開始を許可し続ける
      }
      detected.value = Date.now() - lastVoiceAt < 1500;
    }),
  );
  // レベル計測サイドカーを起動（実マイク）
  try {
    await invoke("start_level", { simulate: null });
  } catch {
    /* マイク無し等は無音ガードで録音開始が抑止される */
  }
});

onUnmounted(() => {
  unlisteners.forEach((u) => u());
  if (isTauri) void invoke("stop_mic").catch(() => undefined);
});

const startRecording = (): void => {
  if (isTauri) void invoke("stop_mic").catch(() => undefined); // level を止めてから録音へ
  // 予定から開始した場合は id を S-05 へ引き継ぐ（その予定に録音・清書・資料を紐づける）。
  router.push(linkedId ? { path: "/s05", query: { id: linkedId } } : "/s05");
};
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

        <!-- 会議サマリ（DD-012-12 Bug#5: 予定の実データを表示） -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">{{ meetingTitle }}</div>
            <div class="text-grey-7">
              参加者: {{ meetingParticipants.length ? meetingParticipants.join("・") : "（登録なし）" }}
            </div>
            <div v-if="meetingAgenda" class="text-grey-7 q-mt-xs" style="white-space: pre-wrap">
              アジェンダ: {{ meetingAgenda }}
            </div>
            <div v-if="meetingVocab.length" class="text-grey-7 q-mt-xs">
              用語: {{ meetingVocab.join(", ") }}
            </div>
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
              <q-item-section avatar>
                <q-icon
                  :name="detected ? 'check_circle' : 'warning'"
                  :color="detected ? 'green-6' : 'amber-7'"
                />
              </q-item-section>
              <q-item-section>
                {{ detected ? "入力を検出（録音できます）" : "マイク入力が検出できません（話すとバーが動きます）" }}
              </q-item-section>
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
                <q-item-label caption>{{ sttModel }}（CPU, n_threads={{ sttThreads }}）</q-item-label>
              </q-item-section>
              <q-item-section side><q-badge color="blue-grey-5" label="設定値" /></q-item-section>
            </q-item>
            <q-item>
              <q-item-section avatar><q-icon name="auto_fix_high" color="primary" /></q-item-section>
              <q-item-section>
                <q-item-label>リアルタイム整形（任意）</q-item-label>
                <q-item-label caption>{{ liveModel }}（追い上げレイヤ）</q-item-label>
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
            :disable="isTauri && !everDetected"
            @click="startRecording"
          >
            <q-tooltip v-if="isTauri && !everDetected">マイク入力を検出してから開始できます</q-tooltip>
          </q-btn>
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
