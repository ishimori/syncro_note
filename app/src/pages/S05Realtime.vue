<script setup lang="ts">
// S-05 リアルタイム議事録（会議中）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-05_realtime.html。
// 「確定テキストが主役（即時・不可変）／LLM整形は薄字の追い上げ」を反映。
// Phase 3-C: Rust(Tauri)経由でPythonサイドカーの文字起こしを listen し、確定タイムラインへ逐次 push する。
//   contract: stt-meta / stt-segment / stt-done / stt-error（DD-011/Phase3_実装前詳細化.md §3）
//   注意: 素のブラウザ(Playwright)には Tauri ランタイムが無く invoke/listen が動かない → ボタンは実ウィンドウ専用。
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useRouter, useRoute } from "vue-router";
import { useQuasar } from "quasar";
import { open } from "@tauri-apps/plugin-dialog";
import AppNav from "../components/AppNav.vue";
import ActiveRecordChip from "../components/ActiveRecordChip.vue";
import {
  localIso,
  getMeetingDetail,
  listAttachments,
  createMeeting,
  updateMeeting,
  addAttachment,
  removeAttachment,
  deleteMeeting,
  type Attachment,
  type Meeting,
  type Participant as DbParticipant,
} from "../api";
import { setActive, titleDate } from "../title";
import { minutesSession, type SessionParticipant } from "../session";
import { useMemoDoc } from "../crdt/memoDoc";
import { startMockAi } from "../crdt/mockAi";

interface AiSeg {
  type: "ai";
  seq: number; // 追い上げ整形(refined)を後から差し込むキー（DD-012-4）
  speaker: string;
  t: string;
  text: string;
  refined: string | null;
  confirmed: boolean;
}
// 人間メモは timeline に混ぜず CRDT(memoDoc) 側で持つ（DD-013）。timeline は AI確定のみ。

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

// 右パネルは録音中に編集できる（DD-016-3/案C）。予定(?id=)から開いた場合は実データで初期化する。
const participants = ref<SessionParticipant[]>([]); // 参加者（名前＋役職）
const agenda = ref<string>(""); // アジェンダ本文
const vocab = ref<string[]>([]); // 専門用語（未永続化のため当面空）
const attachments = ref<Attachment[]>([]); // 事前資料（添付）

// 参加者の表示ラベル（"名前（役職）"）。話者確定プルダウンと右パネル表示に使う。
const labelOf = (p: SessionParticipant): string => (p.role ? `${p.name}（${p.role}）` : p.name);
const participantLabels = computed<string[]>(() => participants.value.map(labelOf));

// 確定話者マッピング（人間確定 > AI推測）
const mapping = reactive<Record<string, string>>({});

// 文字起こしは実データを Rust 経由で受信して積む（初期は空）。
const timeline = reactive<AiSeg[]>([]);

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

// DD-016-1: 会話エリアの独立スクロール＋ヘッダ/操作バー固定。
// ページ高さ＝ビューポート−ヘッダ実測高（bypassバーの増減にも追従）。タイムラインだけ内部スクロールする。
const availH = ref("calc(100vh - 50px)");
const measureHeader = (): void => {
  const h = document.querySelector(".q-header")?.getBoundingClientRect().height ?? 50;
  availH.value = `calc(100vh - ${Math.round(h)}px)`;
};
// 新規セグメントで最下部へ自動追従。ただしユーザーが上方を読んでいる間は追従しない。
const scrollEl = ref<HTMLElement>();
const atBottom = ref(true);
const onScroll = (): void => {
  const el = scrollEl.value;
  if (!el) return;
  atBottom.value = el.scrollHeight - el.clientHeight - el.scrollTop < 40;
};
watch(
  () => timeline.length,
  async () => {
    if (!atBottom.value) return; // 上方閲覧中は追従抑止
    await nextTick();
    const el = scrollEl.value;
    if (el) el.scrollTop = el.scrollHeight;
  },
);

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
// "spk0"/"Speaker_0" などの末尾番号を話者番号(整数)として取り出す。無ければ null（未分離扱い）。
const speakerNum = (speaker: string): number | null => {
  const m = speaker.match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : null;
};
const speakerColor = (speaker: string): string =>
  SPEAKER_COLORS[(speakerNum(speaker) ?? 0) % SPEAKER_COLORS.length];

const assign = (sid: string, name: string): void => {
  mapping[sid] = name;
  timeline.forEach((x) => {
    if (x.type === "ai" && x.speaker === sid) x.confirmed = true;
  });
};

// DD-013: 人間メモは CRDT(Yjs) で保持。AIの自動追記や（将来の）複数人編集と重なっても壊れない。
const memoDoc = useMemoDoc();
const memoText = memoDoc.text;
const memoConflicts = memoDoc.conflictCount;
const onMemoInput = (v: string | number | null): void => {
  memoDoc.setText(v == null ? "" : String(v));
};
// DD-013-3: 左(AI)→右(メモ)コピー。確定セグメントを人間メモ末尾へ取り込む（CRDT挿入＝衝突しない）。
const copyToMemo = (s: AiSeg): void => {
  const prefix = memoText.value.length > 0 && !memoText.value.endsWith("\n") ? "\n" : "";
  memoDoc.append(`${prefix}${displayName(s)}: ${s.text}\n`);
};

// DD-013-1: 模擬AI（dev専用・Tauri不要）。録音なしで「AIが自動追記し続ける」状況を作り、
// 人間メモとの同時編集が壊れないことを Playwright で検証する土俵にする。
const mockRunning = ref(false);
let mockStop: (() => void) | null = null;
const toggleMockAi = (): void => {
  if (mockRunning.value) {
    mockStop?.();
    mockStop = null;
    mockRunning.value = false;
    return;
  }
  mockRunning.value = true;
  mockStop = startMockAi((seg) => {
    timeline.push({
      type: "ai",
      seq: seg.seq,
      speaker: seg.speaker,
      t: fmtMs(seg.seq * 1500),
      text: seg.text,
      refined: null,
      confirmed: false,
    });
  });
};

const router = useRouter();
const route = useRoute();
const ending = ref(false);

// カレンダー(S-01)で予定を開いて来た場合の紐づけ先（?id=）。録音→保存をこの予定へ書き戻す（予定日・タイトル保持）。
const linkedMeetingId = ref<string | null>(null);
const linkedTitle = ref<string>("");
const linkedDate = ref<string>(""); // 紐づく予定の日付（OSウィンドウタイトル表示用）

// DD-016-3/案C: ad-hoc 録音中に事前資料を追加すると、添付に必要な meeting_id を持つ「仮会議」を
// 遅延作成する（status='active'・scheduled_end=NULL＝未保存マーカー。DD-016-2 のスイープ対象）。
const $q = useQuasar();
const tempMeetingId = ref<string | null>(null);
const proceeding = ref(false); // 清書(S-06)へ進む＝離脱だが仮会議は残す（保存まで持ち回り）
// 添付先の会議id（予定>仮会議）。両方無ければ null＝まだ会議行が無い。
const attachMeetingId = computed<string | null>(() => linkedMeetingId.value ?? tempMeetingId.value);

// ── 参加者の編集（録音中に追加・削除） ──
const newName = ref("");
const newRole = ref("");
const addParticipant = (): void => {
  const name = newName.value.trim();
  if (!name) return;
  participants.value.push({ name, role: newRole.value.trim() });
  newName.value = "";
  newRole.value = "";
};
const removeParticipant = (i: number): void => {
  participants.value.splice(i, 1);
};

// ── 事前資料（添付）の追加・削除・抽出プレビュー（S-02/S-03 の作法を流用） ──
const attaching = ref(false);
const fileTypeOf = (name: string): "xlsx" | "pdf" | null => {
  const l = name.toLowerCase();
  if (l.endsWith(".xlsx")) return "xlsx";
  if (l.endsWith(".pdf")) return "pdf";
  return null;
};
const attachIcon = (t: string): string => (t === "xlsx" ? "grid_on" : "picture_as_pdf");
const attachIconColor = (t: string): string => (t === "xlsx" ? "green-7" : "red-7");
const canPreview = (a: Attachment): boolean =>
  a.parse_status === "done" && !!(a.extracted_text && a.extracted_text.trim());
// 抽出テキストのプレビュー（どうテキスト化されたか確認・コピー可）。
const previewOpen = ref(false);
const previewName = ref("");
const previewText = ref("");
const openPreview = (a: Attachment): void => {
  previewName.value = a.file_name;
  previewText.value = a.extracted_text ?? "";
  previewOpen.value = true;
};
const copyPreview = async (): Promise<void> => {
  try {
    await navigator.clipboard.writeText(previewText.value);
    $q.notify({ message: "抽出テキストをコピーしました", color: "indigo", icon: "content_copy", timeout: 1500 });
  } catch {
    $q.notify({ message: "コピーに失敗しました", color: "negative", icon: "error" });
  }
};

// ad-hoc 用の仮タイトル（保存時の会議名と一致させる）。例: 録音メモ 06-09 14:30
const adHocTitle = (): string => `録音メモ ${localIso().slice(5, 16).replace("T", " ")}`;
// 現在の participants を DB Participant[] へ（meeting_id 付き）。
const toDbParticipants = (meetingId: string): DbParticipant[] =>
  participants.value.map((p, i) => ({
    id: crypto.randomUUID(),
    meeting_id: meetingId,
    name: p.name,
    role: p.role || null,
    voice_hint: null,
    sort_order: i,
  }));

// 添付に必要な会議行を確保する。予定(?id=)があればそれ、無ければ仮会議を一度だけ作る（案C）。
const ensureMeeting = async (): Promise<string | null> => {
  if (attachMeetingId.value) return attachMeetingId.value;
  const id = crypto.randomUUID();
  const now = localIso();
  const meeting: Meeting = {
    id,
    title: adHocTitle(),
    agenda: agenda.value || null,
    place: null,
    scheduled_start: now,
    scheduled_end: null, // ← 未保存ad-hoc仮会議マーカー（DD-016-2 スイープ条件）
    actual_start: now,
    actual_end: null,
    status: "active", // ← 仮（保存=S-07 で completed 化）
    final_minutes: null,
    batch_model: null,
    generation_seconds: null,
    audio_path: null,
    created_at: now,
    updated_at: now,
  };
  await createMeeting(meeting, toDbParticipants(id), [], []);
  tempMeetingId.value = id;
  minutesSession.meetingId = id;
  minutesSession.isTempMeeting = true;
  return id;
};

// 「資料を追加」: OSのファイル選択 → 会議を確保 → コピー＋オフライン抽出 → 一覧へ。
const pickAndAttach = async (): Promise<void> => {
  if (!isTauri || attaching.value) return;
  const selected = await open({
    multiple: true,
    filters: [{ name: "資料 (Excel / PDF)", extensions: ["xlsx", "pdf"] }],
  });
  if (selected === null) return;
  const paths = Array.isArray(selected) ? selected : [selected];
  attaching.value = true;
  try {
    const mid = await ensureMeeting();
    if (!mid) return;
    for (const path of paths) {
      const name = path.split(/[\\/]/).pop() ?? path;
      const type = fileTypeOf(name);
      if (!type) {
        $q.notify({ message: `未対応のファイルです: ${name}`, color: "warning", icon: "block" });
        continue;
      }
      const a = await addAttachment(crypto.randomUUID(), mid, path, name, type, localIso());
      attachments.value.push(a);
    }
  } catch (e) {
    $q.notify({ message: `資料の取り込みに失敗しました: ${e}`, color: "negative", icon: "error" });
  } finally {
    attaching.value = false;
  }
};
const removeAttachmentRow = async (a: Attachment): Promise<void> => {
  try {
    await removeAttachment(a.id);
    attachments.value = attachments.value.filter((x) => x.id !== a.id);
  } catch (e) {
    $q.notify({ message: `削除に失敗しました: ${e}`, color: "negative", icon: "error" });
  }
};

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

// 確定タイムライン(AI)＋人間メモ(CRDT)を清書用テキストに整形する（メモは明示ラベルで残す）。
const buildTranscript = (): string => {
  const ai = timeline.map((x) => x.text);
  const memoLines = memoText.value
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
    .map((l) => `【メモ】${l}`);
  return [...ai, ...memoLines].join("\n").trim();
};

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
  // DD-016-3: 右パネルで編集したアジェンダ・参加者を清書セッションへ渡す（保存時に会議へ反映）。
  minutesSession.agenda = agenda.value;
  minutesSession.participants = participants.value.map((p) => ({ ...p }));
  proceeding.value = true; // 清書(S-06)へ進む＝S-05離脱だが仮会議は保存まで残す（onUnmounted で消さない）

  // 会議行の扱いは3通り（DD-016-3/案C）。
  if (linkedMeetingId.value) {
    // 予定を開いて録音した: その予定に紐づけ、保存(S-07)で「完了」へ書き戻す（予定日・タイトルは保持）。
    minutesSession.meetingId = linkedMeetingId.value;
    minutesSession.title = linkedTitle.value || "議事録";
  } else if (tempMeetingId.value) {
    // ad-hoc＋事前資料あり: 仮会議が既にある。最新のアジェンダ・参加者・会議名を書き戻し、保存(S-07)で completed 化。
    minutesSession.meetingId = tempMeetingId.value;
    minutesSession.isTempMeeting = true;
    minutesSession.title = adHocTitle();
    try {
      const now = localIso();
      const row: Meeting = {
        id: tempMeetingId.value,
        title: minutesSession.title,
        agenda: agenda.value || null,
        place: null,
        scheduled_start: now,
        scheduled_end: null,
        actual_start: now,
        actual_end: null,
        status: "active",
        final_minutes: null,
        batch_model: null,
        generation_seconds: null,
        audio_path: null,
        created_at: now,
        updated_at: now,
      };
      await updateMeeting(row, toDbParticipants(tempMeetingId.value));
    } catch {
      /* 書き戻し失敗は致命的でない（作成時の値で保存される） */
    }
  } else {
    // 予定を開かず資料も足していない: 会議行はまだ無い。保存(S-07)で agenda・participants 付き新規会議を作る。
    minutesSession.meetingId = null;
    minutesSession.isTempMeeting = false;
    minutesSession.title = adHocTitle();
  }
  minutesSession.transcript = transcript;
  // 証跡（元タイムライン）も構造化して持ち回り、保存時に timeline_elements へ書き込む。
  // 話者番号を埋める（DD-012-11）→ S-03 で話者表示＋色分けに使う。人間メモは null。
  const aiRows = timeline.map((x) => ({
    kind: "ai_transcription" as const,
    speakerId: speakerNum(x.speaker),
    tMs: clockToMs(x.t),
    text: x.text,
  }));
  // 人間メモ(CRDT本文)は行ごとに human_memo 行へ（話者なし）。確定AIは immutable のまま。
  const memoRows = memoText.value
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
    .map((l) => ({ kind: "human_memo" as const, speakerId: null, tMs: 0, text: l }));
  minutesSession.timeline = [...aiRows, ...memoRows];
  // 人間が確定した話者名（番号→名前）を speaker_mappings 用に集約（確定済みのみ。未確定は S-03 で Speaker_n）。
  const speakerMap = new Map<number, string>();
  timeline.forEach((x) => {
    const n = speakerNum(x.speaker);
    const name = mapping[x.speaker];
    if (n !== null && name) speakerMap.set(n, name);
  });
  minutesSession.speakers = [...speakerMap].map(([speakerId, confirmedName]) => ({
    speakerId,
    confirmedName,
  }));
  minutesSession.finalMarkdown = "";
  minutesSession.batchModel = null;
  minutesSession.generationSeconds = null;
  router.push("/s06");
};

// Tauri イベントの購読/解除（実ウィンドウのみ）。
const unlisteners: UnlistenFn[] = [];
onMounted(async () => {
  // DD-016-1: レイアウト高さの計測（Tauri でも素ブラウザでも必要）。bypassバーの増減にも追従。
  await nextTick();
  measureHeader();
  window.addEventListener("resize", measureHeader);
  watch(bypass, () => nextTick(measureHeader));
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
        // 右パネルを実データで満たす（参加者・アジェンダ・事前資料）。ダミーを排し実際の前提を見せる。
        participants.value = d.participants.map((p) => ({ name: p.name, role: p.role ?? "" }));
        agenda.value = d.meeting.agenda ?? "";
        vocab.value = d.vocab ?? []; // 専門用語を実データに（Bug#7。空なら専門用語セクション非表示）
        attachments.value = await listAttachments(qid);
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
  mockStop?.(); // 模擬AI停止（DD-013-1）
  window.removeEventListener("resize", measureHeader); // DD-016-1
  // DD-016-3/案C: 清書へ進まずに離脱した（＝録音を破棄した）なら、作った仮会議を消す。
  // 進行中(proceeding)は S-06/S-07 へ持ち回るので消さない。取りこぼしは起動時スイープが拾う。
  if (tempMeetingId.value && !proceeding.value) {
    void deleteMeeting(tempMeetingId.value).catch(() => undefined);
    if (minutesSession.meetingId === tempMeetingId.value) {
      minutesSession.meetingId = null;
      minutesSession.isTempMeeting = false;
    }
  }
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
          <!-- アジェンダ: 録音中もその場で編集できる（DD-016-3） -->
          <q-item-label header class="row items-center">
            アジェンダ <q-space />
            <q-icon name="edit" size="16px" color="grey-6"><q-tooltip>録音中も編集できます</q-tooltip></q-icon>
          </q-item-label>
          <q-item>
            <q-item-section>
              <q-input
                v-model="agenda"
                type="textarea"
                outlined
                dense
                autogrow
                placeholder="例）1. 前回宿題の確認 / 2. 仕様レビュー / 3. 次アクション"
              />
            </q-item-section>
          </q-item>
          <q-separator spaced />
          <!-- 参加者: 追加・削除。ここに入れた人は話者確定プルダウンに出る（DD-016-3） -->
          <q-item-label header>参加者</q-item-label>
          <q-item v-if="participants.length === 0">
            <q-item-section class="text-grey-6">（登録なし）</q-item-section>
          </q-item>
          <q-item v-for="(p, i) in participants" :key="i">
            <q-item-section avatar>
              <q-avatar size="28px" color="secondary" text-color="white">{{ (p.name || "？").charAt(0) }}</q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ p.name }}</q-item-label>
              <q-item-label caption v-if="p.role">{{ p.role }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn flat round dense size="sm" icon="close" color="grey-6" @click="removeParticipant(i)">
                <q-tooltip>削除</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>
          <q-item>
            <q-item-section>
              <div class="row q-col-gutter-xs items-center">
                <div class="col-6">
                  <q-input v-model="newName" outlined dense placeholder="名前" @keyup.enter="addParticipant" />
                </div>
                <div class="col">
                  <q-input v-model="newRole" outlined dense placeholder="役職(任意)" @keyup.enter="addParticipant" />
                </div>
                <div class="col-auto">
                  <q-btn round dense color="primary" icon="add" :disable="!newName.trim()" @click="addParticipant">
                    <q-tooltip>参加者を追加</q-tooltip>
                  </q-btn>
                </div>
              </div>
              <div class="text-caption text-grey-6 q-mt-xs">追加した人は左の話者名プルダウンから選べます。</div>
            </q-item-section>
          </q-item>
          <q-separator spaced />
          <!-- 事前資料（DD-012-10/案C・DD-016-3）: 録音中に追加でき、清書に反映される -->
          <q-item-label header class="row items-center">
            事前資料 <q-space />
            <q-icon name="edit" size="16px" color="grey-6"><q-tooltip>録音中も追加できます</q-tooltip></q-icon>
          </q-item-label>
          <q-item v-if="attachments.length === 0">
            <q-item-section class="text-grey-6">（なし）</q-item-section>
          </q-item>
          <q-item v-for="a in attachments" :key="a.id">
            <q-item-section avatar>
              <q-icon :name="attachIcon(a.file_type)" :color="attachIconColor(a.file_type)" />
            </q-item-section>
            <q-item-section>
              <q-item-label lines="1">{{ a.file_name }}</q-item-label>
              <q-item-label caption>
                <span v-if="a.parse_status === 'done' && a.extracted_text" class="text-green-8">清書に反映されます</span>
                <span v-else-if="a.parse_status === 'error'" class="text-negative">抽出失敗</span>
                <span v-else-if="a.parse_status === 'pending'">解析中…</span>
                <span v-else class="text-orange-9">本文なし</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side class="row items-center no-wrap">
              <q-btn
                v-if="canPreview(a)"
                flat
                round
                dense
                size="sm"
                icon="visibility"
                color="primary"
                @click="openPreview(a)"
              >
                <q-tooltip>どうテキスト化されたか確認</q-tooltip>
              </q-btn>
              <q-btn flat round dense size="sm" icon="close" color="grey-6" @click="removeAttachmentRow(a)">
                <q-tooltip>削除</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>
          <q-item>
            <q-item-section>
              <q-btn
                outline
                no-caps
                color="primary"
                icon="attach_file"
                label="資料を追加（Excel/PDF）"
                :loading="attaching"
                :disable="!isTauri || attaching"
                @click="pickAndAttach"
              >
                <q-tooltip v-if="!isTauri">実ウィンドウ（Tauri）でのみ追加できます</q-tooltip>
              </q-btn>
              <div class="text-caption text-grey-6 q-mt-xs">録音中に足した資料も、その後の清書（要約）に反映されます。</div>
            </q-item-section>
          </q-item>
          <template v-if="vocab.length">
            <q-separator spaced />
            <q-item-label header>専門用語</q-item-label>
            <q-item>
              <q-item-section>
                <div class="q-gutter-xs">
                  <q-badge v-for="w in vocab" :key="w" outline color="primary" :label="w" />
                </div>
              </q-item-section>
            </q-item>
          </template>
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
      <q-page class="fill-col" :style="{ height: availH }">
        <div class="q-pa-md fill-col" style="max-width: 1200px; margin: 0 auto; width: 100%; flex: 1 1 auto">
        <!-- 固定領域: 案内バナー＋録音操作バー（スクロールしても残る・DD-016-1） -->
        <div style="flex: 0 0 auto">
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

          <!-- DD-013-1: 模擬AI（dev・Tauri不要）。同時編集の検証用に固定テキストを自動追記。 -->
          <q-btn
            v-if="isDev"
            flat
            dense
            no-caps
            :color="mockRunning ? 'deep-orange-6' : 'teal-6'"
            :icon="mockRunning ? 'stop' : 'smart_toy'"
            :label="mockRunning ? '模擬AI停止' : '模擬AI開始'"
            @click="toggleMockAi"
          >
            <q-tooltip>開発用: 録音なしでAI追記を再現（人間メモとの同時編集テスト）</q-tooltip>
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

        </div>

        <!-- スクロール領域: 左=確定タイムライン（独立スクロール）／右=人間メモ（DD-016-1） -->
        <div class="fill-row" style="flex: 1 1 0; gap: 16px">
          <!-- 左ペイン: 確定タイムライン（AI・主役・immutable）。会話エリアだけ内部スクロール -->
          <div class="fill-col" style="flex: 1 1 0; min-width: 0">
            <q-card flat bordered class="fill-col" style="flex: 1 1 0">
              <div class="timeline-scroll q-pa-md" style="flex: 1 1 0" ref="scrollEl" @scroll="onScroll">
                <div v-for="(s, i) in timeline" :key="i" class="seg">
                  <div class="row items-center">
                    <q-badge :color="speakerColor(s.speaker)" :outline="!s.confirmed" class="q-mr-sm">
                      <span class="spk">{{ displayName(s) }}</span>
                      <q-icon name="arrow_drop_down" />
                      <q-menu>
                        <q-list style="min-width: 180px">
                          <q-item-label header>話者を確定</q-item-label>
                          <q-item v-if="participantLabels.length === 0">
                            <q-item-section class="text-grey-6">右で参加者を追加してください</q-item-section>
                          </q-item>
                          <q-item
                            v-for="p in participantLabels"
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
                    <q-space />
                    <!-- DD-013-3: このセグメントを右の人間メモへコピー -->
                    <q-btn flat dense round size="sm" icon="arrow_forward" color="primary" @click="copyToMemo(s)">
                      <q-tooltip>右の人間メモへコピー</q-tooltip>
                    </q-btn>
                  </div>
                  <div class="q-mt-xs">{{ s.text }}</div>
                  <div v-if="showRefined && s.refined" class="refined">
                    <q-icon name="auto_fix_high" size="14px" /> {{ s.refined }}
                  </div>
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
                  <div v-else>
                    まだ文字起こしはありません。「録音開始」かサンプル、開発用「模擬AI開始」で表示できます。
                  </div>
                </div>
              </div>
            </q-card>
          </div>

          <!-- 右ペイン: 人間メモ（CRDT・同時編集可） DD-013 -->
          <div class="fill-col" style="flex: 0 0 40%; min-width: 0">
            <q-card flat bordered class="fill-col" style="flex: 1 1 0">
              <q-card-section class="q-pb-none" style="flex: 0 0 auto">
                <div class="row items-center">
                  <q-icon name="edit_note" color="orange-8" size="20px" class="q-mr-xs" />
                  <span class="text-subtitle2">人間メモ（同時編集）</span>
                  <q-space />
                  <q-chip
                    dense
                    square
                    color="blue-grey-1"
                    text-color="blue-grey-8"
                    icon="merge"
                    :label="'並行マージ ' + memoConflicts"
                  >
                    <q-tooltip>AI追記や他の人の入力と重なってCRDTがマージした回数（テキスト破壊なし）</q-tooltip>
                  </q-chip>
                </div>
              </q-card-section>
              <div class="q-pa-md" style="flex: 1 1 0; min-height: 0; display: flex">
                <q-input
                  :model-value="memoText"
                  @update:model-value="onMemoInput"
                  type="textarea"
                  outlined
                  class="fit"
                  input-style="height: 100%; resize: none"
                  style="width: 100%"
                  placeholder="📝 ここにメモを書けます。AIの自動追記中でも壊れません。左の文字起こしは → ボタンで取り込めます。"
                />
              </div>
            </q-card>
          </div>
        </div>
        </div>
      </q-page>
    </q-page-container>

    <!-- 人間メモはメイン右ペインの同時編集エディタへ移行（DD-013）。フッタの単一行入力は廃止。 -->

    <!-- 事前資料の抽出テキストプレビュー（どうテキスト化されたか確認・S-02/S-03 と同じ作法・DD-016-3） -->
    <q-dialog v-model="previewOpen">
      <q-card style="width: 720px; max-width: 92vw">
        <q-card-section class="row items-center q-pb-none">
          <q-icon name="description" color="primary" class="q-mr-sm" />
          <div class="text-subtitle1 ellipsis">{{ previewName }}</div>
          <q-space />
          <q-btn flat dense no-caps size="sm" icon="content_copy" label="コピー" color="primary" @click="copyPreview" />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="text-caption text-grey-7 q-pt-xs">
          AIの清書に渡るのと同じ内容です。シート/ページごとに見出し・表へ構造化しています。
        </q-card-section>
        <q-separator />
        <q-card-section>
          <pre class="extract-preview">{{ previewText }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>
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
/* DD-016-1: 会話エリアだけ独立スクロール。Quasar の .row/.column は flex-wrap:wrap を含み
   縦の高さ配分が壊れるため、nowrap の専用クラスで高さを配分する（各階層に min-height:0）。 */
.fill-col {
  display: flex;
  flex-direction: column;
  flex-wrap: nowrap;
  min-height: 0;
}
.fill-row {
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  min-height: 0;
}
.timeline-scroll {
  overflow-y: auto;
  min-height: 0;
}
.extract-preview {
  white-space: pre-wrap;
  font-family: ui-monospace, monospace;
  font-size: 0.82rem;
  max-height: 50vh;
  overflow: auto;
  margin: 0;
}
</style>
