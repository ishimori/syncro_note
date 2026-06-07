<script setup lang="ts">
// S-01 ホーム／カレンダー — Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-01_calendar.html。
// 2026年6月の月カレンダーにダミー会議を配置。チップ／セルのクリックで各画面へ
// ルーター遷移する（completed→/s03, active→/s05, scheduled→/s02）。
// 実データ（DB/予定取得）との接続は後フェーズで行う。
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

type MeetingStatus = "scheduled" | "active" | "completed";

interface Meeting {
  id?: string;
  title: string;
  time: string;
  status: MeetingStatus;
}

interface CalendarCell {
  day: number;
  inMonth: boolean;
  today?: boolean;
  meetings: Meeting[];
}

const leftDrawer = ref(true);
const router = useRouter();

const view = ref<"month" | "week">("month");
const weekdays: string[] = ["日", "月", "火", "水", "木", "金", "土"];

// 2026年6月。ダミー会議を数日に配置。
const meetings: Record<number, Meeting[]> = {
  3: [{ id: "m-youken", title: "要件レビュー", time: "10:00", status: "completed" }],
  9: [{ id: "m-gijutsu", title: "技術選定MTG", time: "14:00", status: "completed" }],
  12: [
    { id: "m-sprint", title: "スプリント計画", time: "09:30", status: "completed" },
    { id: "m-1on1", title: "1on1", time: "17:00", status: "completed" },
  ],
  7: [{ title: "定例会", time: "15:00", status: "active" }], // 今日(=7日)・進行中
  18: [{ title: "設計レビュー", time: "13:00", status: "scheduled" }],
  24: [{ title: "四半期報告", time: "11:00", status: "scheduled" }],
};

const todayDay = 7;
const year = 2026;
const month = 5; // 0-indexed June

const weeks = computed<CalendarCell[][]>(() => {
  const first = new Date(year, month, 1);
  const startOffset = first.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays = new Date(year, month, 0).getDate();
  const cells: CalendarCell[] = [];
  for (let i = 0; i < startOffset; i++) {
    cells.push({ day: prevDays - startOffset + 1 + i, inMonth: false, meetings: [] });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, inMonth: true, today: d === todayDay, meetings: meetings[d] || [] });
  }
  while (cells.length % 7 !== 0) {
    cells.push({ day: cells.length - (startOffset + daysInMonth) + 1, inMonth: false, meetings: [] });
  }
  const out: CalendarCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7));
  return out;
});

const statusColor = (s: MeetingStatus): string =>
  ({ scheduled: "blue-5", active: "red-5", completed: "green-6" })[s] || "grey";

const statusIcon = (s: MeetingStatus): string =>
  ({ scheduled: "event", active: "fiber_manual_record", completed: "check" })[s] || "event";

// 過去/完了→議事録詳細(/s03)、進行中→会議画面(/s05)、当日/未来→会議作成(/s02)
const linkFor = (m: Meeting): string =>
  m.status === "completed" ? "/s03" : m.status === "active" ? "/s05" : "/s02";
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
          <div class="text-h5 q-mr-md">2026年 6月</div>
          <q-btn flat round dense icon="chevron_left" />
          <q-btn flat round dense icon="chevron_right" />
          <q-btn outline no-caps dense label="今日" class="q-ml-sm" />
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
          <span class="q-ml-md">過去/完了をクリック→議事録詳細、当日/未来→会議作成、進行中→会議画面</span>
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
                @click="router.push(linkFor(m))"
              >
                <q-icon :name="statusIcon(m.status)" size="14px" class="q-mr-xs" />
                {{ m.time }} {{ m.title }}
              </q-chip>
            </div>
          </div>
        </q-card>

        <q-banner dense rounded class="bg-grey-2 q-mt-md text-grey-8">
          <template v-slot:avatar><q-icon name="info" color="primary" /></template>
          これは静的モックです。日付セルやチップのクリックで各画面へ遷移します（ダミーデータ）。
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
