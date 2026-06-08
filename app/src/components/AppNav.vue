<script setup lang="ts">
// 左ドロワーの画面ナビ。全画面で共有する。
// クリックでルーター遷移し、現在の画面をハイライト。開閉は v-model で
// 各画面ヘッダの☰ボタンと同期する（デスクトップでは show-if-above で常時表示）。
//
// メニュー構成（DD-015・最終形）:
//  ・常設（PRODUCT）= 製品でも出す入口。カレンダー / 今すぐ録音 / 設定 の3つ。
//    「今すぐ録音」は予定なしでその場録音する入口 → /s04（id無し ad-hoc プリフライト）。
//  ・開発専用（DEV_LINKS）= S-02〜S-07 の生画面への直行リンク。import.meta.env.DEV の
//    ときだけ表示し、DEV バッジを付ける（製品ビルド `vite build` では非表示）。
//  ・WIP バッジは全廃（各画面は実装・動作確認済み）。
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

// 開発ビルド（tauri dev / vite serve）でのみ DEV リンクを出す。製品ビルドでは false。
const showDev = import.meta.env.DEV;

interface NavItem {
  name: string;
  icon: string;
  to: string;
}
// 製品の常設メニュー（クリーン表示・バッジ無し）。
const PRODUCT: NavItem[] = [
  { name: "カレンダー", icon: "calendar_month", to: "/s01" },
  { name: "今すぐ録音", icon: "mic", to: "/s04" }, // 予定なし ad-hoc 録音の入口（DD-015）
  { name: "設定", icon: "settings", to: "/s08" },
];
// 開発専用: 各画面へ直接飛べるデバッグ導線（DEV バッジ）。製品では非表示。
const DEV_LINKS: (NavItem & { id: string })[] = [
  { id: "S-02", name: "会議作成", icon: "event_note", to: "/s02" },
  { id: "S-03", name: "議事録詳細", icon: "description", to: "/s03" },
  { id: "S-04", name: "プリフライト", icon: "mic", to: "/s04" },
  { id: "S-05", name: "リアルタイム", icon: "graphic_eq", to: "/s05" },
  { id: "S-06", name: "生成中", icon: "auto_awesome", to: "/s06" },
  { id: "S-07", name: "プレビュー", icon: "fact_check", to: "/s07" },
];

const isActive = (to: string): boolean => route.path === to;
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
      <!-- 常設（製品メニュー）: 名前のみ・バッジ無しのクリーン表示 -->
      <q-item
        v-for="n in PRODUCT"
        :key="n.to"
        clickable
        :active="isActive(n.to)"
        active-class="bg-indigo-1 text-primary text-weight-bold"
        @click="router.push(n.to)"
      >
        <q-item-section avatar><q-icon :name="n.icon" /></q-item-section>
        <q-item-section>
          <q-item-label>{{ n.name }}</q-item-label>
        </q-item-section>
      </q-item>

      <!-- 開発専用リンク（製品ビルドでは非表示）。S-0X id ＋ DEV バッジ。 -->
      <template v-if="showDev">
        <q-separator spaced />
        <q-item-label header class="text-grey-7 text-caption">開発用（製品では非表示）</q-item-label>
        <q-item
          v-for="n in DEV_LINKS"
          :key="n.id"
          clickable
          :active="isActive(n.to)"
          active-class="bg-indigo-1 text-primary text-weight-bold"
          @click="router.push(n.to)"
        >
          <q-item-section avatar><q-icon :name="n.icon" /></q-item-section>
          <q-item-section>
            <q-item-label>{{ n.id }}</q-item-label>
            <q-item-label caption>{{ n.name }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-badge color="red-6" text-color="white" label="DEV" class="text-weight-bold">
              <q-tooltip>製品ではメニューに出さない画面（モーダル/フローで開く）。開発用の直行リンク。</q-tooltip>
            </q-badge>
          </q-item-section>
        </q-item>
      </template>
    </q-list>
  </q-drawer>
</template>
