// 「いまアクティブなレコード（会議名＋日付＋状態）」を一元管理し、2か所へ同時表示する。
//   1) OSウィンドウのタイトル（タイトルバー / タスクバー / Alt+Tab）… 既定の "app" 固定の代わり。
//   2) アプリ内ヘッダのチップ（components/ActiveRecordChip.vue）… 画面の中でも「今どれを見ているか」を出す。
// 使い方: 画面ごとに setActive({ screen, name?, date?, state? }) を呼ぶ。会議を扱わない画面は name を省けばチップは隠れる。
//   画面遷移のたびに router(afterEach) が setActive({ screen }) で一旦リセットするので、前画面の表示は残らない。
// 注意: setTitle は Tauri ランタイム上でのみ動く（素のブラウザ/Playwright では no-op）。権限=core:window:allow-set-title。
import { reactive } from "vue";
import { getCurrentWindow } from "@tauri-apps/api/window";

const APP_NAME = "SynchroniNote";
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** アプリ内ヘッダのチップ（ActiveRecordChip）が読む共有状態。setActive で更新する。 */
export interface ActiveRecord {
  name: string; // 会議名（無ければ空＝チップは隠れる）
  date: string; // "YYYY/MM/DD"（無ければ空）
  state: string; // 例 "● 録音中"（無ければ空）
}
export const activeRecord = reactive<ActiveRecord>({ name: "", date: "", state: "" });

/** OSウィンドウのタイトルだけを直接更新する低レベル関数（context 無しは "SynchroniNote"）。
 *  飾りなので失敗（権限差異・タイミング）は握りつぶす。 */
export const setAppTitle = (context?: string): void => {
  if (!isTauri) return;
  const c = context?.trim();
  void getCurrentWindow()
    .setTitle(c ? `${c} — ${APP_NAME}` : APP_NAME)
    .catch(() => undefined);
};

/** 画面の「いま開いているレコード」を設定する。アプリ内チップとOSタイトルの両方へ反映。
 *  name が無い画面（カレンダー/設定など）は screen だけ出し、チップは隠れる。 */
export const setActive = (opts: {
  screen: string;
  name?: string;
  date?: string;
  state?: string;
}): void => {
  activeRecord.name = opts.name?.trim() ?? "";
  activeRecord.date = opts.date?.trim() ?? "";
  activeRecord.state = opts.state?.trim() ?? "";
  // OSタイトル: "会議名 日付 状態・画面名 — SynchroniNote"（レコード無しなら "画面名"）。
  const rec = [activeRecord.name, activeRecord.date, activeRecord.state].filter(Boolean).join(" ");
  setAppTitle(rec ? `${rec}・${opts.screen}` : opts.screen);
};

/** ローカルISO "YYYY-MM-DDTHH:MM:SS" → "YYYY/MM/DD"（表示用）。空や不正は空文字。 */
export const titleDate = (iso: string | null | undefined): string =>
  iso && iso.length >= 10 ? iso.slice(0, 10).replace(/-/g, "/") : "";
