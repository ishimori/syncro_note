// 画面ルーティング定義（S-01〜S-08）。
// 全画面ともモック由来の静的画面を表示する（バックエンド未接続）。
// 実装状況（実機ロジック接続済みか）は AppNav の WIP バッジで示す。
// Tauri はファイルから index.html を読むため、サーバ側フォールバック不要な
// ハッシュ履歴（/#/s05）を使う（リロードや asset パスで 404 にならない）。
import { createRouter, createWebHashHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import S01Calendar from "../pages/S01Calendar.vue";
import S02CreateMeeting from "../pages/S02CreateMeeting.vue";
import S03MinutesDetail from "../pages/S03MinutesDetail.vue";
import S04Preflight from "../pages/S04Preflight.vue";
import S05Realtime from "../pages/S05Realtime.vue";
import S06Generating from "../pages/S06Generating.vue";
import S07MinutesPreview from "../pages/S07MinutesPreview.vue";
import S08Settings from "../pages/S08Settings.vue";

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/s01" },
  { path: "/s01", component: S01Calendar },
  { path: "/s02", component: S02CreateMeeting },
  { path: "/s03", component: S03MinutesDetail },
  { path: "/s04", component: S04Preflight },
  { path: "/s05", component: S05Realtime },
  { path: "/s06", component: S06Generating },
  { path: "/s07", component: S07MinutesPreview },
  { path: "/s08", component: S08Settings },
  // 未知のパスはホーム（カレンダー）へ
  { path: "/:pathMatch(.*)*", redirect: "/s01" },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
