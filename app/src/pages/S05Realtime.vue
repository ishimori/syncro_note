<script setup lang="ts">
// S-05 リアルタイム議事録（会議中）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-05_realtime.html。
// 「確定テキストが主役（即時・不可変）／LLM整形は薄字の追い上げ」を反映。
// Phase 3-C: Rust(Tauri)経由でPythonサイドカーの文字起こしを listen し、確定タイムラインへ逐次 push する。
//   contract: stt-meta / stt-segment / stt-done / stt-error（DD-011/Phase3_実装前詳細化.md §3）
//   注意: 素のブラウザ(Playwright)には Tauri ランタイムが無く invoke/listen が動かない → ボタンは実ウィンドウ専用。
import { ref, reactive, onMounted, onUnmounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import AppNav from "../components/AppNav.vue";

interface AiSeg {
  type: "ai";
  speaker: string;
  t: string;
  text: string;
  refined: string | null;
  confirmed: boolean;
}
interface MemoSeg {
  type: "memo";
  t: string;
  text: string;
}
type TimelineItem = AiSeg | MemoSeg;

// サイドカー契約のイベントペイロード（DD-011 §3）
interface MetaEvent {
  duration_s?: number; // mic（ライブ）は音声長未確定 → 無し
  mode?: string; // "mic" のときライブ録音
  model: string;
  language: string;
}
interface SegmentEvent {
  seq: number;
  text: string;
  t_start_ms: number;
  t_end_ms: number;
}
interface DoneEvent {
  count: number;
  elapsed_s: number;
}
interface ErrorEvent {
  message: string;
  where?: string;
}

const leftDrawer = ref(true);

const drawer = ref(true);
const showRefined = ref(true);
const bypass = ref(false);
const elapsed = ref("00:00:00");
const latency = ref(0);
const drops = ref(0);

const participants = ["鈴木（PM）", "佐藤（エンジニア）", "田中（デザイナー）"];
const vocab = ["Qwen", "Tauri", "SQLite", "SynchroniNote", "diarization"];

// 確定話者マッピング（人間確定 > AI推測）
const mapping = reactive<Record<string, string>>({});

// 文字起こしは実データを Rust 経由で受信して積む（初期は空）。
const timeline = reactive<TimelineItem[]>([]);

// 文字起こしの状態（UIの合図）。Phase 3-C で追加、DD-012-1 で recording/paused を追加。
type SttStatus = "idle" | "preparing" | "running" | "recording" | "paused" | "done" | "error";
const status = ref<SttStatus>("idle");
const durationS = ref(0);
const doneCount = ref(0);
const errorMsg = ref("");
const isMic = ref(false); // 直近セッションがマイク（ライブ）か
const isDev = import.meta.env.DEV; // dev専用UI（疑似マイク等）。本番ビルドでは出さない

// 素ブラウザ(Playwright)には Tauri ランタイムが無い → ボタンを無効化してフォールバック。
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

// ミリ秒 → "mm:ss"
const fmtMs = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
};

const resetSession = (): void => {
  timeline.length = 0;
  doneCount.value = 0;
  errorMsg.value = "";
  status.value = "preparing"; // meta 受信まで「準備中」スピナー
};

const startSample = async (): Promise<void> => {
  if (!isTauri) return;
  isMic.value = false;
  resetSession();
  try {
    await invoke("start_transcription", { audioPath: "audio/sample01.wav" }); // STTモデルは S-08 設定（DD-012-7）
  } catch (e) {
    status.value = "error";
    errorMsg.value = String(e);
  }
};

// マイク録音（DD-012-1）。simulate 指定時はファイルを mic 代替で流す（dev/テスト・実マイク不要）。
const startMic = async (simulate?: string): Promise<void> => {
  if (!isTauri) return;
  resetSession();
  try {
    await invoke("start_mic", { simulate: simulate ?? null }); // STTモデル/スレッドは S-08 設定（DD-012-7）
  } catch (e) {
    status.value = "error";
    errorMsg.value = String(e);
  }
};
const pauseMic = async (): Promise<void> => {
  try {
    await invoke("pause_mic");
    status.value = "paused"; // サイドカーは pause で何も emit しない → 楽観更新
  } catch (e) {
    errorMsg.value = String(e);
  }
};
const resumeMic = async (): Promise<void> => {
  try {
    await invoke("resume_mic");
    status.value = "recording";
  } catch (e) {
    errorMsg.value = String(e);
  }
};
const stopMic = async (): Promise<void> => {
  try {
    await invoke("stop_mic"); // 停止は stt-done 受信で status→done になる
  } catch (e) {
    errorMsg.value = String(e);
  }
};

const displayName = (s: AiSeg): string => mapping[s.speaker] || s.speaker;

const assign = (sid: string, name: string): void => {
  mapping[sid] = name;
  timeline.forEach((x) => {
    if (x.type === "ai" && x.speaker === sid) x.confirmed = true;
  });
};

const memo = ref("");
const sendMemo = (): void => {
  if (memo.value.trim()) {
    timeline.push({ type: "memo", t: elapsed.value.slice(3), text: memo.value });
    memo.value = "";
  }
};

// Tauri イベントの購読/解除（実ウィンドウのみ）。
const unlisteners: UnlistenFn[] = [];
onMounted(async () => {
  if (!isTauri) return;
  unlisteners.push(
    await listen<MetaEvent>("stt-meta", (e) => {
      durationS.value = e.payload.duration_s ?? 0;
      isMic.value = e.payload.mode === "mic";
      status.value = isMic.value ? "recording" : "running"; // mic は録音中 / file は受信中
    }),
    await listen<SegmentEvent>("stt-segment", (e) => {
      const p = e.payload;
      timeline.push({
        type: "ai",
        speaker: "Speaker_0", // 話者分離は範囲外（暫定固定）
        t: fmtMs(p.t_start_ms),
        text: p.text,
        refined: null, // LLM整形は範囲外
        confirmed: false, // 話者は人間未確定
      });
      elapsed.value = "00:" + fmtMs(p.t_end_ms); // ヘッダの経過＝直近セグメント終端
    }),
    await listen<DoneEvent>("stt-done", (e) => {
      doneCount.value = e.payload.count;
      status.value = "done";
    }),
    await listen<ErrorEvent>("stt-error", (e) => {
      errorMsg.value = e.payload.message;
      status.value = "error";
    }),
  );
});
onUnmounted(() => {
  unlisteners.forEach((u) => u());
});
</script>

<template>
  <q-layout view="hHh LpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 録音状態・経過・遅延ゲージ・drop・終了 -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <span v-if="status === 'recording'" class="rec-dot q-mr-sm" />
        <q-toolbar-title>設計レビュー{{ status === "recording" ? " — 録音中" : "" }}</q-toolbar-title>
        <q-chip dense color="white" text-color="primary" icon="schedule" :label="elapsed" class="q-mr-sm" />
        <q-chip
          dense
          :color="latency > 3 ? 'red-4' : 'green-4'"
          text-color="white"
          icon="speed"
          :label="'遅延 ' + latency + 's'"
          class="q-mr-sm"
        >
          <q-tooltip>整形バックログ（主役の確定表示は0遅延）</q-tooltip>
        </q-chip>
        <q-chip dense color="grey-4" text-color="dark" icon="warning" :label="'drop ' + drops" />
        <q-btn unelevated no-caps color="red-6" icon="stop" label="会議を終了" class="q-ml-md" />
      </q-toolbar>
      <q-bar class="bg-indigo-2 text-indigo-10" v-if="bypass">
        <q-icon name="bolt" /> 処理が詰まったため LLM整形をバイパス中（生テキストを優先表示）
      </q-bar>
    </q-header>

    <!-- 右ドロワー: コンテキスト参照（デスクトップでは常時ドッキング＝背景を暗くしない） -->
    <q-drawer side="right" v-model="drawer" show-if-above bordered :width="280">
      <q-scroll-area class="fit">
        <q-list padding>
          <q-item-label header>アジェンダ</q-item-label>
          <q-item>
            <q-item-section>1. 基本設計のレビュー<br />2. 話者分離方式の確定<br />3. DD候補</q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item-label header>参加者</q-item-label>
          <q-item v-for="p in participants" :key="p">
            <q-item-section avatar>
              <q-avatar size="28px" color="secondary" text-color="white">{{ p.charAt(0) }}</q-avatar>
            </q-item-section>
            <q-item-section>{{ p }}</q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item-label header>専門用語</q-item-label>
          <q-item>
            <q-item-section>
              <div class="q-gutter-xs">
                <q-badge v-for="w in vocab" :key="w" outline color="primary" :label="w" />
              </div>
            </q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item>
            <q-item-section>
              <q-toggle v-model="showRefined" label="LLM整形を表示" color="primary" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>
    </q-drawer>

    <!-- メイン: 確定タイムライン（主役）＋人間メモ -->
    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 900px; margin: 0 auto">
        <q-banner dense rounded class="bg-amber-1 q-mb-sm text-grey-9">
          <template v-slot:avatar><q-icon name="info" color="amber-8" /></template>
          <b>確定文字起こしが主役</b>（即時・不可変）。LLM整形は薄い字の<b>追い上げ表示</b>。話者名をクリックすると参加者から選んで一括置換できます。
          <q-btn flat dense round icon="menu_open" @click="drawer = !drawer" class="float-right">
            <q-tooltip>コンテキスト</q-tooltip>
          </q-btn>
        </q-banner>

        <!-- 録音操作（実ウィンドウ専用）＋状態表示。DD-012-1（マイク）＋ Phase 3-C（サンプル） -->
        <div class="row items-center q-mb-sm q-gutter-sm">
          <!-- マイク録音（DD-012-1） -->
          <q-btn
            v-if="status !== 'recording' && status !== 'paused'"
            unelevated
            no-caps
            color="red-6"
            icon="mic"
            label="録音開始"
            :disable="!isTauri || status === 'preparing'"
            @click="startMic()"
          >
            <q-tooltip v-if="!isTauri">実ウィンドウ（Tauri）でのみ実行できます</q-tooltip>
          </q-btn>
          <q-btn
            v-if="status === 'recording'"
            unelevated
            no-caps
            color="amber-7"
            icon="pause"
            label="一時停止"
            @click="pauseMic"
          />
          <q-btn
            v-if="status === 'paused'"
            unelevated
            no-caps
            color="green-6"
            icon="play_arrow"
            label="再開"
            @click="resumeMic"
          />
          <q-btn
            v-if="status === 'recording' || status === 'paused'"
            unelevated
            no-caps
            color="grey-7"
            icon="stop"
            label="停止"
            @click="stopMic"
          />

          <!-- サンプル音声（DD-011 3-C・ファイル一括） -->
          <q-btn
            flat
            no-caps
            color="primary"
            icon="play_arrow"
            label="サンプルを流す"
            :disable="
              !isTauri ||
              status === 'preparing' ||
              status === 'running' ||
              status === 'recording' ||
              status === 'paused'
            "
            @click="startSample"
          >
            <q-tooltip v-if="!isTauri">実ウィンドウ（Tauri）でのみ実行できます</q-tooltip>
          </q-btn>

          <!-- dev専用: 疑似マイク（実マイク不要で mic 経路を検証） -->
          <q-btn
            v-if="isDev"
            flat
            dense
            no-caps
            color="purple-5"
            icon="science"
            label="疑似マイク"
            :disable="!isTauri || status === 'preparing' || status === 'recording' || status === 'paused'"
            @click="startMic('audio/sample01.wav')"
          >
            <q-tooltip>開発用: sample01.wav を mic 経路に流す</q-tooltip>
          </q-btn>

          <!-- 状態チップ -->
          <q-chip v-if="status === 'preparing'" dense color="amber-3" text-color="grey-9" icon="hourglass_top">
            準備中… <q-spinner-dots color="amber-8" size="1.2em" class="q-ml-xs" />
          </q-chip>
          <q-chip v-else-if="status === 'recording'" dense color="red-2" text-color="red-10" icon="mic">
            録音中（{{ elapsed.slice(3) }}）
          </q-chip>
          <q-chip v-else-if="status === 'paused'" dense color="amber-3" text-color="grey-9" icon="pause">
            一時停止中
          </q-chip>
          <q-chip v-else-if="status === 'running'" dense color="blue-2" text-color="blue-10" icon="graphic_eq">
            文字起こし中（音声長 {{ fmtMs(durationS * 1000) }}）
          </q-chip>
          <q-chip v-else-if="status === 'done'" dense color="green-3" text-color="green-10" icon="check_circle">
            完了（{{ doneCount }}件）
          </q-chip>
          <q-chip v-else-if="status === 'error'" dense color="red-3" text-color="red-10" icon="error">
            エラー: {{ errorMsg }}
          </q-chip>
          <q-chip v-else dense color="grey-3" text-color="grey-8" icon="info">
            「録音開始」かサンプルで開始
          </q-chip>
        </div>

        <q-card flat bordered>
          <q-card-section>
            <div v-for="(s, i) in timeline" :key="i">
              <!-- 人間メモ -->
              <template v-if="s.type === 'memo'">
                <q-chat-message :name="'📝人間メモ'" :text="[s.text]" :stamp="s.t" sent bg-color="orange-2" />
              </template>
              <!-- AI確定セグメント -->
              <template v-else>
                <div class="seg">
                  <div class="row items-center">
                    <q-badge :color="s.confirmed ? 'secondary' : 'grey-5'" class="q-mr-sm">
                      <span class="spk">{{ displayName(s) }}</span>
                      <q-icon name="arrow_drop_down" />
                      <q-menu>
                        <q-list style="min-width: 180px">
                          <q-item-label header>話者を確定</q-item-label>
                          <q-item
                            v-for="p in participants"
                            :key="p"
                            clickable
                            v-close-popup
                            @click="assign(s.speaker, p)"
                          >
                            <q-item-section>{{ p }}</q-item-section>
                          </q-item>
                        </q-list>
                      </q-menu>
                    </q-badge>
                    <span class="text-caption text-grey-6">{{ s.t }}</span>
                    <q-badge v-if="!s.refined" outline color="grey-6" label="unrefined" class="q-ml-sm">
                      <q-tooltip>整形待ち（生テキスト表示中）</q-tooltip>
                    </q-badge>
                  </div>
                  <div class="q-mt-xs">{{ s.text }}</div>
                  <div v-if="showRefined && s.refined" class="refined">
                    <q-icon name="auto_fix_high" size="14px" /> {{ s.refined }}
                  </div>
                </div>
              </template>
            </div>
            <!-- 受信待ち（タイムラインが空のとき） -->
            <div v-if="timeline.length === 0" class="text-grey-6 q-pa-md text-center">
              <q-icon name="graphic_eq" size="28px" class="q-mb-xs" />
              <div v-if="status === 'preparing'">モデル読込中… 最初の文字起こしまで少しかかります</div>
              <div v-else-if="status === 'recording' || status === 'paused'">
                マイク入力待ち…（話すと文字が出ます）
              </div>
              <div v-else>まだ文字起こしはありません。「録音開始」かサンプルで開始してください。</div>
            </div>
          </q-card-section>
        </q-card>
        <div style="height: 80px" />
      </q-page>
    </q-page-container>

    <!-- フッタ: 人間メモ入力 -->
    <q-footer class="bg-white text-dark" bordered>
      <q-toolbar class="q-py-sm" style="max-width: 900px; margin: 0 auto; width: 100%">
        <q-btn flat round dense icon="pause" color="grey-7"><q-tooltip>一時停止</q-tooltip></q-btn>
        <q-input
          class="col q-mx-sm"
          outlined
          dense
          v-model="memo"
          placeholder="📝 人間メモを入力（ホワイトボードの内容・口頭指示など）… Enterで挿入"
          @keyup.enter="sendMemo"
        >
          <template v-slot:prepend><q-icon name="edit_note" /></template>
        </q-input>
        <q-btn round color="primary" icon="send" @click="sendMemo" />
      </q-toolbar>
    </q-footer>
  </q-layout>
</template>

<style scoped>
.rec-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  display: inline-block;
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
.refined {
  color: #64748b;
  font-size: 0.85em;
  border-left: 2px solid #cbd5e1;
  padding-left: 8px;
  margin-top: 2px;
}
.spk {
  cursor: pointer;
  border-bottom: 1px dashed #94a3b8;
}
.seg {
  border-bottom: 1px solid #f1f5f9;
  padding: 8px 0;
}
</style>
