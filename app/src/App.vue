<script setup lang="ts">
// 画面ルーティングのホスト。左ナビ(AppNav)は各画面側に内包するため、
// ここでは router-view のみを置く（既定は S-05 にリダイレクト）。
</script>

<template>
  <router-view />
</template>

<!-- モック準拠の Quasar ブランドカラー（インディゴ/ティール）。グローバル適用のため scoped にしない -->
<style>
:root {
  --q-primary: #4f46e5;
  --q-secondary: #0ea5a4;
}
</style>
