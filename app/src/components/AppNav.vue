<script setup lang="ts">
// 左ドロワーの画面ナビ（S-01〜S-08）。全画面で共有する。
// クリックでルーター遷移し、現在の画面をハイライト。開閉は v-model で
// 各画面ヘッダの☰ボタンと同期する（デスクトップでは show-if-above で常時表示）。
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ "update:modelValue": [boolean] }>();

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

const route = useRoute();
const router = useRouter();

interface NavItem {
  id: string;
  name: string;
  icon: string;
  to: string;
  // 実機ロジック未接続（モック表示のみ）の画面は WIP バッジを出す。
  // 画面が本実装できたら false にする（= バッジが消える）。
  wip: boolean;
}
const NAV: NavItem[] = [
  { id: "S-01", name: "カレンダー", icon: "calendar_month", to: "/s01", wip: true },
  { id: "S-02", name: "会議作成", icon: "event_note", to: "/s02", wip: true },
  { id: "S-03", name: "議事録詳細", icon: "description", to: "/s03", wip: true },
  { id: "S-04", name: "プリフライト", icon: "mic", to: "/s04", wip: true },
  { id: "S-05", name: "リアルタイム", icon: "graphic_eq", to: "/s05", wip: true },
  { id: "S-06", name: "生成中", icon: "auto_awesome", to: "/s06", wip: true },
  { id: "S-07", name: "プレビュー", icon: "fact_check", to: "/s07", wip: true },
  { id: "S-08", name: "設定", icon: "settings", to: "/s08", wip: true },
];
</script>

<template>
  <q-drawer
    side="left"
    v-model="open"
    show-if-above
    bordered
    :width="230"
    class="bg-grey-1"
  >
    <q-toolbar class="bg-primary text-white">
      <q-avatar icon="graphic_eq" size="28px" />
      <q-toolbar-title class="text-subtitle1">SynchroniNote</q-toolbar-title>
    </q-toolbar>
    <q-list padding>
      <q-item
        v-for="n in NAV"
        :key="n.id"
        clickable
        :active="route.path === n.to"
        active-class="bg-indigo-1 text-primary text-weight-bold"
        @click="router.push(n.to)"
      >
        <q-item-section avatar><q-icon :name="n.icon" /></q-item-section>
        <q-item-section>
          <q-item-label>{{ n.id }}</q-item-label>
          <q-item-label caption>{{ n.name }}</q-item-label>
        </q-item-section>
        <q-item-section side v-if="n.wip">
          <q-badge color="orange-5" text-color="white" label="WIP" class="text-weight-bold">
            <q-tooltip>未実装（モック表示のみ）</q-tooltip>
          </q-badge>
        </q-item-section>
      </q-item>
    </q-list>
  </q-drawer>
</template>
