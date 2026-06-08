// 画面ルーティング定義（S-01〜S-08）。
// 全画面ともモック由来の静的画面を表示する（バックエンド未接続）。
// 実装状況（実機ロジック接続済みか）は AppNav の WIP バッジで示す。
// Tauri はファイルから index.html を読むため、サーバ側フォールバック不要な
// ハッシュ履歴（/#/s05）を使う（リロードや asset パスで 404 にならない）。
import { createRouter, createWebHashHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import { setActive } from "../title";
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

// 画面ごとの基本タイトル（OSタイトル＋アプリ内チップの土台）。会議を扱う画面は、各画面が
// 読み込んだ会議名＋日付で setActive を上書きする（その前段の既定値としてここで必ずセットする）。
const SCREEN_TITLE: Record<string, string> = {
  "/s01": "カレンダー",
  "/s02": "会議の作成",
  "/s03": "議事録詳細",
  "/s04": "プリフライト",
  "/s05": "リアルタイム議事録",
  "/s06": "議事録を生成中",
  "/s07": "議事録プレビュー",
  "/s08": "設定",
};
router.afterEach((to) => {
  // 画面の基本タイトルをセットしつつ、アクティブ会議をリセット（前画面のチップを残さない）。
  // 会議を扱う画面は、各画面が読み込み後に setActive で会議名＋日付を上書きする。
  setActive({ screen: SCREEN_TITLE[to.path] ?? "" });
});
