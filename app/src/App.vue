<script setup lang="ts">
// Phase 2: 中核画面 S-05（リアルタイム議事録）の静的骨格を表示する。
// 複数画面のルーティングは後続フェーズ。現時点は S-05 単体をホストする。
import S05Realtime from "./pages/S05Realtime.vue";
</script>

<template>
  <S05Realtime />
</template>

<!-- モック準拠の Quasar ブランドカラー（インディゴ/ティール）。グローバル適用のため scoped にしない -->
<style>
:root {
  --q-primary: #4f46e5;
  --q-secondary: #0ea5a4;
}
</style>
