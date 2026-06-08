<script setup lang="ts">
// S-01 ホーム／カレンダー — DD-012-3 で SQLite 実データ表示、DD-012-9 で操作強化。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/DD/DD-012-9/mock/S-01_calendar.html。
// 当月の会議を Rust(Tauri)経由で SQLite から読み込み、月カレンダーに配置する。
// DD-012-9 で追加した操作（いずれも実DB・invoke は実ウィンドウ専用）:
//   - チップ全体クリックで操作メニュー（開く/編集/書き出し(completedのみ)/削除）
//   - チップを別日へドラッグ&ドロップして予定日時を更新（scheduled/completed のみ・時刻と所要時間は維持）
//   - 削除は確認ダイアログ→数秒の「元に戻す」（削除前に詳細を退避し create_meeting で再作成）
//   - 空きセルの＋でその日の新規会議作成へ
// dev では確認用シード(seed_demo・冪等)を投入してから読み込む（DD-012-3-1）。
//   注意: invoke は Tauri ランタイム上でのみ動く（素のブラウザ/Playwright では不可）。
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useQuasar } from "quasar";
import AppNav from "../components/AppNav.vue";
import {
  listMeetings,
  seedDemo,
  deleteMeeting,
  updateMeetingSchedule,
  getMeetingDetail,
  createMeeting,
  localIso,
  type Meeting as DbMeeting,
  type MeetingDetail,
  type MeetingStatus,
} from "../api";

const leftDrawer = ref(true);
const router = useRouter();
const $q = useQuasar();

const weekdays: string[] = ["日", "月", "火", "水", "木", "金", "土"];

const today = new Date();
const cursor = ref(new Date(today.getFullYear(), today.getMonth(), 1)); // 表示中の月の1日
const dbMeetings = ref<DbMeeting[]>([]);
const loading = ref(false);
const errorMsg = ref("");

const year = computed<number>(() => cursor.value.getFullYear());
const month0 = computed<number>(() => cursor.value.getMonth()); // 0-indexed
const monthLabel = computed<string>(() => `${year.value}年 ${month0.value + 1}月`);

// 当月の会議をDBから読み込む（dev はシード投入してから）。
const load = async (): Promise<void> => {
  loading.value = true;
  errorMsg.value = "";
  try {
    const y = year.value;
    const m = month0.value + 1; // 1-12
    if (import.meta.env.DEV) {
      try {
        await seedDemo(y, m); // 確認用シード（冪等・dev のみ）
      } catch {
        /* シード失敗は致命ではない（本番DBや権限差異）。読み込みは続行 */
      }
    }
    dbMeetings.value = await listMeetings(y, m);
  } catch (e) {
    errorMsg.value = String(e);
    dbMeetings.value = [];
  } finally {
    loading.value = false;
  }
};
onMounted(load);

const prevMonth = (): void => {
  cursor.value = new Date(year.value, month0.value - 1, 1);
  void load();
};
const nextMonth = (): void => {
  cursor.value = new Date(year.value, month0.value + 1, 1);
  void load();
};
const goToday = (): void => {
  cursor.value = new Date(today.getFullYear(), today.getMonth(), 1);
  void load();
};

interface CellMeeting {
  id: string;
  title: string;
  time: string;
  status: MeetingStatus;
}
interface CalendarCell {
  day: number;
  inMonth: boolean;
  today?: boolean;
  meetings: CellMeeting[];
}

// scheduled_start("YYYY-MM-DDTHH:MM:SS") から 日 と 時刻(HH:MM) を取り出す。
const dayOf = (iso: string): number => Number(iso.slice(8, 10));
const timeOf = (iso: string): string => iso.slice(11, 16);

// "YYYY-MM-DDTHH:MM:SS" をローカル時刻として解釈する（new Date(string) はUTC扱いの罠があるため手組み）。
const parseLocalIso = (iso: string): Date => {
  const [d, t] = iso.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi, s] = (t || "00:00:00").split(":").map(Number);
  return new Date(y, mo - 1, da, h || 0, mi || 0, s || 0);
};

const byDay = computed<Record<number, CellMeeting[]>>(() => {
  const map: Record<number, CellMeeting[]> = {};
  for (const m of dbMeetings.value) {
    const d = dayOf(m.scheduled_start);
    (map[d] ||= []).push({ id: m.id, title: m.title, time: timeOf(m.scheduled_start), status: m.status });
  }
  for (const d in map) map[d].sort((a, b) => a.time.localeCompare(b.time));
  return map;
});

const isToday = (d: number): boolean =>
  today.getFullYear() === year.value && today.getMonth() === month0.value && today.getDate() === d;

const weeks = computed<CalendarCell[][]>(() => {
  const first = new Date(year.value, month0.value, 1);
  const startOffset = first.getDay();
  const daysInMonth = new Date(year.value, month0.value + 1, 0).getDate();
  const prevDays = new Date(year.value, month0.value, 0).getDate();
  const cells: CalendarCell[] = [];
  for (let i = 0; i < startOffset; i++) {
    cells.push({ day: prevDays - startOffset + 1 + i, inMonth: false, meetings: [] });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, inMonth: true, today: isToday(d), meetings: byDay.value[d] || [] });
  }
  while (cells.length % 7 !== 0) {
    cells.push({ day: cells.length - (startOffset + daysInMonth) + 1, inMonth: false, meetings: [] });
  }
  const out: CalendarCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7));
  return out;
});

const statusColor = (s: MeetingStatus): string =>
  ({ scheduled: "blue-5", active: "red-5", generating: "orange-6", completed: "green-6", aborted: "grey-6" })[s] ||
  "grey";

const statusIcon = (s: MeetingStatus): string =>
  ({ scheduled: "event", active: "fiber_manual_record", generating: "autorenew", completed: "check", aborted: "block" })[
    s
  ] || "event";

// ===== 操作メニュー =====
// completed→議事録詳細(/s03 に id)、進行中/生成中→会議画面(/s05)、その他→会議作成(/s02)
const openMeeting = (m: CellMeeting): void => {
  if (m.status === "completed") router.push({ path: "/s03", query: { id: m.id } });
  else if (m.status === "active" || m.status === "generating") router.push("/s05");
  else router.push("/s02");
};

// 編集（DD-012-9 Phase 4）: S-02 を編集モード（?id=）で開く。
const editMeeting = (m: CellMeeting): void => {
  router.push({ path: "/s02", query: { id: m.id } });
};

// 書き出し（DD-012-9 Phase 4）: 完了議事録(Markdown)をクリップボードへコピー（依存なし）。
const exportMinutes = async (m: CellMeeting): Promise<void> => {
  const md = dbMeetings.value.find((x) => x.id === m.id)?.final_minutes ?? "";
  if (!md) {
    $q.notify({ message: "この会議には書き出せる議事録がありません", color: "orange-8", icon: "info" });
    return;
  }
  try {
    await navigator.clipboard.writeText(md);
    $q.notify({ message: `「${m.title}」の議事録をコピーしました`, color: "indigo", icon: "content_copy", timeout: 2000 });
  } catch {
    $q.notify({ message: "コピーに失敗しました", color: "negative", icon: "error" });
  }
};

// ===== 空きセルから新規作成 =====
const createAt = (cell: CalendarCell): void => {
  if (!cell.inMonth) return;
  const date = `${year.value}-${String(month0.value + 1).padStart(2, "0")}-${String(cell.day).padStart(2, "0")}`;
  router.push({ path: "/s02", query: { date } });
};

// ===== ドラッグ&ドロップで移動 =====
// 暴発防止: scheduled / completed のみドラッグ可（進行中 active・生成中 generating は動かさない）。
const canDrag = (s: MeetingStatus): boolean => s === "scheduled" || s === "completed";
const draggingId = ref<string | null>(null);
const dragOverDay = ref<number | null>(null);

const onDragStart = (m: CellMeeting, ev: DragEvent): void => {
  if (!canDrag(m.status)) {
    ev.preventDefault();
    return;
  }
  draggingId.value = m.id;
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = "move";
};
const onDragEnd = (): void => {
  draggingId.value = null;
  dragOverDay.value = null;
};
const onDragOver = (cell: CalendarCell): void => {
  if (cell.inMonth) dragOverDay.value = cell.day;
};
const onDragLeave = (cell: CalendarCell): void => {
  if (dragOverDay.value === cell.day) dragOverDay.value = null;
};
const onDrop = async (cell: CalendarCell): Promise<void> => {
  const id = draggingId.value;
  draggingId.value = null;
  dragOverDay.value = null;
  if (!id || !cell.inMonth) return;
  const m = dbMeetings.value.find((x) => x.id === id);
  if (!m) return;
  const oldStart = parseLocalIso(m.scheduled_start);
  // 同じ日へのドロップは何もしない。
  if (
    oldStart.getFullYear() === year.value &&
    oldStart.getMonth() === month0.value &&
    oldStart.getDate() === cell.day
  ) {
    return;
  }
  // 時刻は維持し日付だけ差し替え、終了は元の所要時間を保って平行移動。
  const newStart = new Date(
    year.value,
    month0.value,
    cell.day,
    oldStart.getHours(),
    oldStart.getMinutes(),
    oldStart.getSeconds(),
  );
  const prevStartIso = m.scheduled_start;
  const prevEndIso = m.scheduled_end;
  let newEndIso: string | null = null;
  if (m.scheduled_end) {
    const dur = parseLocalIso(m.scheduled_end).getTime() - oldStart.getTime();
    newEndIso = localIso(new Date(newStart.getTime() + dur));
  }
  try {
    await updateMeetingSchedule(id, localIso(newStart), newEndIso, localIso());
    await load();
    $q.notify({
      message: `「${m.title}」を ${month0.value + 1}/${cell.day} へ移動しました`,
      color: "primary",
      icon: "event",
      timeout: 3000,
      actions: [
        {
          label: "元に戻す",
          color: "amber",
          handler: () => {
            void updateMeetingSchedule(id, prevStartIso, prevEndIso ?? null, localIso()).then(load);
          },
        },
      ],
    });
  } catch (e) {
    errorMsg.value = String(e);
  }
};

// ===== 削除（確認＋元に戻す） =====
const askDelete = (m: CellMeeting): void => {
  $q.dialog({
    title: "削除の確認",
    message: `「${m.title}」を削除します。よろしいですか？<br><span style="color:#9ca3af;font-size:12px">参加者・文字起こしも一緒に消えます</span>`,
    html: true,
    persistent: true,
    cancel: { label: "キャンセル", flat: true, color: "grey-8" },
    ok: { label: "削除", color: "negative", unelevated: true },
  }).onOk(() => void doDelete(m));
};
const doDelete = async (m: CellMeeting): Promise<void> => {
  try {
    // 元に戻す用に、削除前の詳細（本体＋参加者＋タイムライン）を退避する。
    const snap = await getMeetingDetail(m.id);
    await deleteMeeting(m.id);
    await load();
    $q.notify({
      message: `「${m.title}」を削除しました`,
      color: "grey-9",
      icon: "delete",
      timeout: 6000,
      actions: snap
        ? [{ label: "元に戻す", color: "amber", handler: () => void restore(snap) }]
        : [],
    });
  } catch (e) {
    errorMsg.value = String(e);
  }
};
const restore = async (snap: MeetingDetail): Promise<void> => {
  try {
    await createMeeting(snap.meeting, snap.participants, snap.timeline);
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="graphic_eq" />
        <q-toolbar-title>SynchroniNote</q-toolbar-title>
        <q-btn flat dense no-caps icon="add" label="新規会議" @click="router.push('/s02')" class="q-mr-sm" />
        <q-btn flat round dense icon="settings" @click="router.push('/s08')">
          <q-tooltip>設定</q-tooltip>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 1100px; margin: 0 auto">
        <!-- 月ナビ -->
        <div class="row items-center q-mb-md">
          <div class="text-h5 q-mr-md">{{ monthLabel }}</div>
          <q-btn flat round dense icon="chevron_left" @click="prevMonth" />
          <q-btn flat round dense icon="chevron_right" @click="nextMonth" />
          <q-btn outline no-caps dense label="今日" class="q-ml-sm" @click="goToday" />
          <q-spinner v-if="loading" color="primary" size="20px" class="q-ml-sm" />
          <q-space />
        </div>

        <!-- 凡例 -->
        <div class="row q-gutter-sm q-mb-sm items-center text-caption text-grey-7">
          <q-badge color="blue-5" label="予約 scheduled" />
          <q-badge color="red-5" label="進行中 active" />
          <q-badge color="green-6" label="完了 completed" />
          <span class="q-ml-md">予定をクリック→メニュー（開く/編集/書き出し/削除）／ドラッグで別日へ移動</span>
        </div>

        <!-- カレンダー -->
        <q-card flat bordered>
          <div class="row text-center q-py-xs">
            <div class="col cal-head" v-for="w in weekdays" :key="w">{{ w }}</div>
          </div>
          <div class="row" v-for="(week, wi) in weeks" :key="wi">
            <div
              class="col cal-cell q-pa-xs"
              v-for="(d, di) in week"
              :key="di"
              :class="{ dim: !d.inMonth, today: d.today, dragover: dragOverDay === d.day && d.inMonth }"
              @dragover.prevent="onDragOver(d)"
              @dragleave="onDragLeave(d)"
              @drop="onDrop(d)"
            >
              <!-- 日付行＋空き枠の＋ -->
              <div class="row items-center no-wrap">
                <div class="text-weight-medium">{{ d.day }}</div>
                <q-badge v-if="d.today" color="primary" class="q-ml-xs">今日</q-badge>
                <q-space />
                <q-btn
                  v-if="d.inMonth"
                  flat
                  dense
                  round
                  size="9px"
                  icon="add"
                  color="primary"
                  class="add-btn"
                  @click="createAt(d)"
                >
                  <q-tooltip>この日に会議を作成</q-tooltip>
                </q-btn>
              </div>

              <!-- 予定/議事録チップ（全体クリックでメニュー、ドラッグで移動） -->
              <!-- ドラッグは外側の div で受ける（q-chip clickable のリップルが HTML5 ドラッグ開始を飲むため） -->
              <div
                v-for="m in d.meetings"
                :key="m.id"
                class="meet-wrap q-mt-xs"
                :class="{ 'meet-wrap--drag': canDrag(m.status) }"
                :draggable="canDrag(m.status)"
                @dragstart="onDragStart(m, $event)"
                @dragend="onDragEnd"
              >
                <q-chip
                  dense
                  clickable
                  class="meet-chip q-ma-none full-width justify-start no-wrap"
                  :color="statusColor(m.status)"
                  text-color="white"
                >
                  <q-icon :name="statusIcon(m.status)" size="14px" class="q-mr-xs" />
                  <span class="ellipsis">{{ m.time }} {{ m.title }}</span>
                  <q-icon name="expand_more" size="14px" class="q-ml-auto" />
                  <q-menu auto-close anchor="bottom left" self="top left">
                    <q-list dense style="min-width: 168px">
                      <q-item-label header class="q-py-xs ellipsis" style="max-width: 240px">
                        {{ m.time }} {{ m.title }}
                      </q-item-label>
                      <q-item clickable @click="openMeeting(m)">
                        <q-item-section avatar><q-icon name="open_in_new" /></q-item-section>
                        <q-item-section>開く</q-item-section>
                      </q-item>
                      <q-item clickable @click="editMeeting(m)">
                        <q-item-section avatar><q-icon name="edit" /></q-item-section>
                        <q-item-section>編集</q-item-section>
                      </q-item>
                      <q-item v-if="m.status === 'completed'" clickable @click="exportMinutes(m)">
                        <q-item-section avatar><q-icon name="download" /></q-item-section>
                        <q-item-section>書き出し</q-item-section>
                      </q-item>
                      <q-separator />
                      <q-item clickable @click="askDelete(m)" class="text-negative">
                        <q-item-section avatar><q-icon name="delete" color="negative" /></q-item-section>
                        <q-item-section>削除</q-item-section>
                      </q-item>
                    </q-list>
                  </q-menu>
                </q-chip>
              </div>
            </div>
          </div>
        </q-card>

        <q-banner v-if="errorMsg" dense rounded class="bg-orange-2 q-mt-md text-orange-10">
          <template v-slot:avatar><q-icon name="warning" color="orange-9" /></template>
          会議の読み込みに失敗しました（Tauri ランタイム上で実行していますか？）: {{ errorMsg }}
        </q-banner>
        <q-banner v-else dense rounded class="bg-grey-2 q-mt-md text-grey-8">
          <template v-slot:avatar><q-icon name="storage" color="primary" /></template>
          SQLite の実データを表示しています（{{ dbMeetings.length }} 件 / {{ monthLabel }}）。
        </q-banner>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.cal-cell {
  min-height: 104px;
  border: 1px solid #e5e7eb;
  position: relative;
  transition: background 0.12s, outline 0.12s;
}
.cal-cell.dim {
  background: #fafafa;
  color: #bbb;
}
.cal-cell.today {
  outline: 2px solid var(--q-primary);
  outline-offset: -2px;
}
.cal-cell.dragover {
  outline: 2px dashed var(--q-secondary);
  outline-offset: -2px;
  background: #ecfeff;
}
.cal-head {
  font-size: 12px;
  color: #6b7280;
}
.meet-wrap {
  width: 100%;
}
.meet-wrap--drag {
  cursor: grab;
}
.meet-wrap--drag:active {
  cursor: grabbing;
}
.meet-chip {
  font-size: 11px;
  cursor: pointer;
}
/* 空き枠の「＋」はセルにホバーした時だけ薄く出す */
.add-btn {
  opacity: 0;
  transition: opacity 0.12s;
}
.cal-cell:hover .add-btn {
  opacity: 0.55;
}
.add-btn:hover {
  opacity: 1;
}
</style>
