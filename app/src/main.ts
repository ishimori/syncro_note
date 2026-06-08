import { createApp } from "vue";
import { Quasar, Notify, Dialog } from "quasar";
import App from "./App.vue";
import { router } from "./router";

// Quasar のアイコン・スタイル（プリビルドCSSを使用。sass-embedded はプラグインが利用）
import "@quasar/extras/material-icons/material-icons.css";
import "quasar/dist/quasar.css";

// Notify/Dialog: S-01 の削除確認・「元に戻す」スナックバー等で使用（DD-012-9）
createApp(App).use(Quasar, { plugins: { Notify, Dialog } }).use(router).mount("#app");
