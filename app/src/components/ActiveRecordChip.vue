<script setup lang="ts">
// アプリ内ヘッダ用「いまアクティブな会議」チップ。共有状態 activeRecord（title.ts）を読むだけ。
// 各画面の <q-toolbar> に <ActiveRecordChip /> を置くと、開いている会議名＋日付（＋録音状態）を常時表示する。
// 会議を扱わない画面（カレンダー/設定など）では name が空なので自動的に隠れる。
import { activeRecord } from "../title";
</script>

<template>
  <q-chip
    v-if="activeRecord.name"
    dense
    color="white"
    text-color="primary"
    icon="event_note"
    class="active-rec-chip q-ml-sm"
    :title="`${activeRecord.name} ${activeRecord.date} ${activeRecord.state}`.trim()"
  >
    <span class="ellipsis">{{ activeRecord.name }}</span>
    <span v-if="activeRecord.date" class="q-ml-xs text-caption">{{ activeRecord.date }}</span>
    <span v-if="activeRecord.state" class="q-ml-xs text-weight-medium">・{{ activeRecord.state }}</span>
  </q-chip>
</template>

<style scoped>
.active-rec-chip {
  max-width: 360px; /* 長い会議名は省略（ヘッダのボタンを押し出さない） */
}
</style>
