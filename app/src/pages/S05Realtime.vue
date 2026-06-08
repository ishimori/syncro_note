<script setup lang="ts">
// S-05 リアルタイム議事録（会議中）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-05_realtime.html。
// 「確定テキストが主役（即時・不可変）／LLM整形は薄字の追い上げ」を反映。
// Phase 3-C: Rust(Tauri)経由でPythonサイドカーの文字起こしを listen し、確定タイムラインへ逐次 push する。
//   contract: stt-meta / stt-segment / stt-done / stt-error（DD-011/Phase3_実装前詳細化.md §3）
//   注意: 素のブラウザ(Playwright)には Tauri ランタイムが無く invoke/listen が動かない → ボタンは実ウィンドウ専用。
import { ref, reactive, computed, onMounted, onUnmounted, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useRouter, useRoute } from "vue-router";
import AppNav from "../components/AppNav.vue";
import ActiveRecordChip from "../components/ActiveRecordChip.vue";
import { localIso, getMeetingDetail } from "../api";
import { setActive, titleDate } from "../title";
import { minutesSession } from "../session";

interface AiSeg {
  type: "ai";
  seq: number; // 追い上げ整形(refined)を後から差し込むキー（DD-012-4）
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
  refine?: boolean; // 追い上げ整形が動いているか（DD-012-4・バッジ判定）
}
interface SegmentEvent {
  seq: number;
  text: string;
  t_start_ms: number;
  t_end_ms: number;
  speaker?: string; // DD-012-5 話者ラベル（file=確定値 / mic=暫定spk0→stt-speakersで置換）
}
interface DoneEvent {
  count: number;
  elapsed_s: number;
}
interface ErrorEvent {
  message: string;
  where?: string;
}
// DD-012-4 追い上げ整形イベント
interface RefinedEvent {
  seq: number;
  text: string;
}
interface BypassEvent {
  on: boolean;
}
// DD-012-5 会議後一括の話者ラベル（seq→話者ID）。mic は停止時にまとめて届く。
interface SpeakersEvent {
  map: Record<string, string>;
}

const leftDrawer = ref(true);

const drawer = ref(true);
const showRefined = ref(true); // 整形の「表示」ON/OFF（計算は止めない）
const liveRefine = ref(false); // 整形の「実行」ON/OFF（今回ぶん・CPU負荷）。設定値で初期化（DD-012-4）
const refineActive = ref(false); // 実際に整形が動いている録音か（meta 由来・バッジ判定）
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

// 案2（DD-010-1）: 「認識中…」の見える化（フロントのみ・STT非依存）。
// 長い発話は区切り（無音 or 最大10秒）が来るまで文字にならず、その間「壊れた?」と
// 誤解されやすい。録音中で直近の確定から少し間が空いたら「認識中…」を出し、
// ちゃんと動作中だと分かるようにする（混乱防止の最小策）。
const nowMs = ref(0);
let lastSegAt = 0; // 直近に確定セグメントが届いた時刻（録音開始でリセット）
let aliveTimer: ReturnType<typeof setInterval> | undefined;
const startAlive = (): void => {
  lastSegAt = Date.now();
  nowMs.value = Date.now();
  if (aliveTimer === undefined) {
    aliveTimer = setInterval(() => {
      nowMs.value = Date.now();
    }, 500);
  }
};
const stopAlive = (): void => {
  if (aliveTimer !== undefined) {
    clearInterval(aliveTimer);
    aliveTimer = undefined;
  }
};
// 録音中で、直近の確定から ~1.2秒 以上あいている＝今まさに音声をためて認識中。
const recognizing = computed(() => status.value === "recording" && nowMs.value - lastSegAt > 1200);
const waitingS = computed(() => Math.max(0, Math.floor((nowMs.value - lastSegAt) / 1000)));

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
    await invoke("start_mic", { simulate: simulate ?? null, refine: liveRefine.value }); // STT=S-08設定 / 整形=今回トグル(DD-012-4)
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
    startAlive(); // 再開時も認識中表示の時計を回す（案2）
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

// 話者ごとに安定した配色（視認性向上・DD-012-5）。spk0/spk1… の末尾番号で色を決めるので、
// 同じ話者は常に同じ色（確定や遡及ラベルで色が飛ばない）。確定済み=塗り／未確定=アウトラインで
// 「誰か」と「確定済みか」を同時に表す。
const SPEAKER_COLORS = [
  "blue-6",
  "deep-orange-6",
  "green-6",
  "purple-5",
  "teal-6",
  "pink-5",
  "indigo-5",
  "brown-5",
];
const speakerColor = (speaker: string): string => {
  const m = speaker.match(/(\d+)$/);
  const idx = m ? parseInt(m[1], 10) : 0;
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length];
};

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

const router = useRouter();
const route = useRoute();
const ending = ref(false);

// カレンダー(S-01)で予定を開いて来た場合の紐づけ先（?id=）。録音→保存をこの予定へ書き戻す（予定日・タイトル保持）。
const linkedMeetingId = ref<string | null>(null);
const linkedTitle = ref<string>("");
const linkedDate = ref<string>(""); // 紐づく予定の日付（OSウィンドウタイトル表示用）

// ヘッダのチップとOSタイトルに「会議名＋日付＋録音状態」を出す（タスクバー/Alt+Tabでも録音中だと分かる）。
watch(
  [linkedTitle, linkedDate, status],
  () => {
    const state =
      status.value === "recording" ? "● 録音中" : status.value === "paused" ? "⏸ 一時停止中" : "";
    setActive({
      screen: "リアルタイム議事録",
      name: linkedTitle.value,
      date: linkedDate.value,
      state,
    });
  },
  { immediate: true },
);

// 確定タイムライン＋人間メモを清書用テキストに整形する（メモは明示ラベルで残す）。
const buildTranscript = (): string =>
  timeline
    .map((x) => (x.type === "memo" ? `【メモ】${x.text}` : x.text))
    .join("\n")
    .trim();

// "mm:ss" → ミリ秒（証跡 timeline の t_ms 用）。壊れていれば 0。
const clockToMs = (t: string): number => {
  const p = t.split(":").map((n) => parseInt(n, 10));
  if (p.length === 2 && p.every((n) => !Number.isNaN(n))) return (p[0] * 60 + p[1]) * 1000;
  return 0;
};

// 「会議を終了」: 録音を止め、清書元テキストと会議名を清書(S-06)へ渡す（DB作成は保存時=S-07）。
const endMeeting = async (): Promise<void> => {
  if (!isTauri || ending.value) return;
  ending.value = true; // 二重起動防止（stop_mic 待ちの間の再クリックを弾く）
  // 録音中/一時停止中なら停止（done を待たず楽観的に進む）。
  if (status.value === "recording" || status.value === "paused") {
    try {
      await invoke("stop_mic");
    } catch {
      /* 停止失敗でも清書は続行（サイドカーは清書spawn時にkillされる） */
    }
  }
  const transcript = buildTranscript();
  if (!transcript) {
    status.value = "error";
    errorMsg.value = "文字起こしがありません（先に録音してください）";
    ending.value = false;
    return;
  }
  // 会議はまだDBに作らない（保存するまで未保存の「生成中」を残さない）。
  // 清書元と会議名だけ次画面へ渡し、実際の作成/書き戻しは S-07 の保存時に行う。
  if (linkedMeetingId.value) {
    // 予定を開いて録音した: その予定に紐づけ、保存(S-07)で「完了」へ書き戻す（予定日・タイトルは保持）。
    minutesSession.meetingId = linkedMeetingId.value;
    minutesSession.title = linkedTitle.value || "議事録";
  } else {
    // 予定を開かずその場で録音した: 今日の新規会議として保存する（従来どおり）。
    minutesSession.meetingId = null;
    minutesSession.title = `録音メモ ${localIso().slice(5, 16).replace("T", " ")}`; // 例: 録音メモ 06-08 14:30
  }
  minutesSession.transcript = transcript;
  // 証跡（元タイムライン）も構造化して持ち回り、保存時に timeline_elements へ書き込む。
  minutesSession.timeline = timeline.map((x) => ({
    kind: x.type === "memo" ? ("human_memo" as const) : ("ai_transcription" as const),
    speakerId: null, // 話者分離は未実装
    tMs: clockToMs(x.t),
    text: x.text,
  }));
  minutesSession.finalMarkdown = "";
  minutesSession.batchModel = null;
  minutesSession.generationSeconds = null;
  router.push("/s06");
};

// Tauri イベントの購読/解除（実ウィンドウのみ）。
const unlisteners: UnlistenFn[] = [];
onMounted(async () => {
  if (!isTauri) return;
  // 整形トグルの初期値を設定（use_llm_live）から取る。読めなければ既定OFF（DD-012-4）。
  try {
    const s = await invoke<{ use_llm_live: boolean }>("get_settings");
    liveRefine.value = s.use_llm_live;
  } catch {
    /* 既定OFFのまま */
  }
  // 予定から開いた場合(?id=)は紐づけ先を取得。録音→保存(S-07)でその予定を「完了」へ書き戻す。
  const qid = typeof route.query.id === "string" ? route.query.id : "";
  if (qid) {
    try {
      const d = await getMeetingDetail(qid);
      if (d) {
        linkedMeetingId.value = d.meeting.id;
        linkedTitle.value = d.meeting.title;
        linkedDate.value = titleDate(d.meeting.scheduled_start);
      }
    } catch {
      /* 取得失敗時はその場録音として続行（新規保存にフォールバック） */
    }
  }
  unlisteners.push(
    await listen<MetaEvent>("stt-meta", (e) => {
      durationS.value = e.payload.duration_s ?? 0;
      isMic.value = e.payload.mode === "mic";
      refineActive.value = e.payload.refine ?? false; // この録音で整形が動いているか
      status.value = isMic.value ? "recording" : "running"; // mic は録音中 / file は受信中
      if (isMic.value) startAlive(); // 認識中表示の時計を開始（案2・DD-010-1）
    }),
    await listen<SegmentEvent>("stt-segment", (e) => {
      const p = e.payload;
      timeline.push({
        type: "ai",
        seq: p.seq, // refined / 話者ラベルを後から差し込むためのキー（DD-012-4 / 012-5）
        speaker: p.speaker ?? "Speaker_0", // 実話者（無ければ暫定固定）DD-012-5
        t: fmtMs(p.t_start_ms),
        text: p.text,
        refined: null, // 追い上げ整形（stt-refined）が後から入る
        confirmed: false, // 話者は人間未確定
      });
      elapsed.value = "00:" + fmtMs(p.t_end_ms); // ヘッダの経過＝直近セグメント終端
      lastSegAt = Date.now(); // 確定が来たら認識中の待ち時計をリセット（案2）
    }),
    await listen<DoneEvent>("stt-done", (e) => {
      doneCount.value = e.payload.count;
      status.value = "done";
      stopAlive(); // 認識中表示の時計を停止（案2）
    }),
    await listen<ErrorEvent>("stt-error", (e) => {
      errorMsg.value = e.payload.message;
      status.value = "error";
      stopAlive(); // 認識中表示の時計を停止（案2）
    }),
    // DD-012-4: 追い上げ整形。該当 seq の確定行に薄字 refined を後から差し込む。
    await listen<RefinedEvent>("stt-refined", (e) => {
      const seg = timeline.find((x) => x.type === "ai" && x.seq === e.payload.seq);
      if (seg && seg.type === "ai") seg.refined = e.payload.text;
    }),
    // DD-012-4: 整形が詰まったらバイパス（ヘッダのバナー表示）。
    await listen<BypassEvent>("stt-bypass", (e) => {
      bypass.value = e.payload.on;
    }),
    // DD-012-5: 会議後一括の話者ラベル。既存セグメントの話者を seq で後追い置換する（mic 経路）。
    await listen<SpeakersEvent>("stt-speakers", (e) => {
      const m = e.payload.map;
      timeline.forEach((x) => {
        if (x.type !== "ai") return;
        const spk = m[String(x.seq)];
        if (spk) {
          x.speaker = spk;
          x.confirmed = mapping[spk] != null; // 既に人間確定済みの話者なら確定表示を維持
        }
      });
    }),
  );
});
onUnmounted(() => {
  unlisteners.forEach((u) => u());
  stopAlive(); // タイマー解放（案2）
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
        <q-toolbar-title>リアルタイム議事録</q-toolbar-title>
        <ActiveRecordChip />
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
        <q-btn
          unelevated
          no-caps
          color="red-6"
          icon="stop"
          label="会議を終了"
          class="q-ml-md"
          :disable="!isTauri || ending || timeline.length === 0"
          @click="endMeeting"
        >
          <q-tooltip v-if="!isTauri">実ウィンドウ（Tauri）でのみ実行できます</q-tooltip>
          <q-tooltip v-else-if="timeline.length === 0">先に録音して文字起こしを作成してください</q-tooltip>
        </q-btn>
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

          <!-- リアルタイム整形 ON/OFF（今回ぶん・CPU負荷。録音中は変更不可）DD-012-4 -->
          <q-toggle
            v-if="status !== 'recording' && status !== 'paused'"
            v-model="liveRefine"
            dense
            color="primary"
            icon="auto_fix_high"
            label="リアルタイム整形"
            :disable="!isTauri"
          >
            <q-tooltip>会議中にAIで文字を整える（CPU負荷増）。OFFで軽くなります。既定は設定(S-08)に従う</q-tooltip>
          </q-toggle>

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

          <!-- 案2（DD-010-1）: 認識中の見える化。「録音中」チップと並べ、長い発話で確定が出ない間も動作中だと示す。 -->
          <q-chip v-if="recognizing" dense color="deep-orange-2" text-color="deep-orange-10" icon="graphic_eq">
            認識中… 約{{ waitingS }}秒ぶんを処理中
            <q-spinner-dots color="deep-orange-9" size="1.1em" class="q-ml-xs" />
            <q-tooltip>長い発話は区切りがつくまで文字になりません（仕様）。処理は動いています</q-tooltip>
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
                    <q-badge :color="speakerColor(s.speaker)" :outline="!s.confirmed" class="q-mr-sm">
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
                    <q-badge
                      v-if="!s.refined && refineActive"
                      outline
                      color="grey-6"
                      label="unrefined"
                      class="q-ml-sm"
                    >
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
                <template v-if="recognizing">
                  ● 認識中…（最初の区切りまで少しかかります。長い発話はまとまってから文字になります）
                </template>
                <template v-else>マイク入力待ち…（話すと文字が出ます）</template>
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
