import { createApp } from "vue";
import { Quasar } from "quasar";
import App from "./App.vue";

// Quasar のアイコン・スタイル（プリビルドCSSを使用。sass-embedded はプラグインが利用）
import "@quasar/extras/material-icons/material-icons.css";
import "quasar/dist/quasar.css";

createApp(App).use(Quasar, { plugins: {} }).mount("#app");
