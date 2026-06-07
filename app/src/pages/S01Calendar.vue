<script setup lang="ts">
// S-01 ホーム／カレンダー — DD-012-3 Phase 2: SQLite 実データ表示。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-01_calendar.html。
// 当月の会議を Rust(Tauri)経由で SQLite から読み込み、月カレンダーに配置する。
// dev では確認用シード(seed_demo・冪等)を投入してから読み込む（DD-012-3-1）。
// チップのクリックで遷移: completed→/s03(id付), active/generating→/s05, その他→/s02。
//   注意: invoke は Tauri ランタイム上でのみ動く（素のブラウザ/Playwright では不可）。
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";
import { listMeetings, seedDemo, type Meeting as DbMeeting, type MeetingStatus } from "../api";

const leftDrawer = ref(true);
const router = useRouter();

const view = ref<"month" | "week">("month");
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

// completed→議事録詳細(/s03 に id)、進行中/生成中→会議画面(/s05)、その他→会議作成(/s02)
const openMeeting = (m: CellMeeting): void => {
  if (m.status === "completed") router.push({ path: "/s03", query: { id: m.id } });
  else if (m.status === "active" || m.status === "generating") router.push("/s05");
  else router.push("/s02");
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
          <q-btn-toggle
            v-model="view"
            no-caps
            unelevated
            toggle-color="primary"
            :options="[
              { label: '月', value: 'month' },
              { label: '週', value: 'week' },
            ]"
          />
        </div>

        <!-- 凡例 -->
        <div class="row q-gutter-sm q-mb-sm items-center text-caption text-grey-7">
          <q-badge color="blue-5" label="予約 scheduled" />
          <q-badge color="red-5" label="進行中 active" />
          <q-badge color="green-6" label="完了 completed" />
          <span class="q-ml-md">完了をクリック→議事録詳細、当日/未来→会議作成、進行中→会議画面</span>
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
              :class="{ dim: !d.inMonth, today: d.today }"
            >
              <div class="row items-center">
                <div class="text-weight-medium">{{ d.day }}</div>
                <q-badge v-if="d.today" color="primary" class="q-ml-xs">今日</q-badge>
              </div>
              <q-chip
                v-for="(m, mi) in d.meetings"
                :key="mi"
                dense
                clickable
                class="meet-chip q-ma-none q-mt-xs full-width justify-start"
                :color="statusColor(m.status)"
                text-color="white"
                @click="openMeeting(m)"
              >
                <q-icon :name="statusIcon(m.status)" size="14px" class="q-mr-xs" />
                {{ m.time }} {{ m.title }}
              </q-chip>
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
}
.cal-cell.dim {
  background: #fafafa;
  color: #bbb;
}
.cal-cell.today {
  outline: 2px solid var(--q-primary);
  outline-offset: -2px;
}
.cal-head {
  font-size: 12px;
  color: #6b7280;
}
.meet-chip {
  font-size: 11px;
  cursor: pointer;
}
</style>
