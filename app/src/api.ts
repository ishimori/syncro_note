// SQLite データへの型付き invoke ラッパー（DD-012-3 Phase 2）。
// Rust の Tauri command(db_commands.rs)を1:1で呼ぶ。フィールド名は Rust 構造体(snake_case)に一致させる
// （ネスト構造体は serde がそのまま読むため。トップレベル引数のみ camelCase 自動変換が効く）。
//
// 注意: invoke は Tauri ランタイム上でのみ動く。素のブラウザ(Playwright)では失敗する → 実ウィンドウ専用。
import { invoke } from "@tauri-apps/api/core";

export type MeetingStatus = "scheduled" | "active" | "generating" | "completed" | "aborted";

export interface Meeting {
  id: string;
  title: string;
  agenda: string | null;
  place: string | null;
  scheduled_start: string; // ローカルISO8601（無TZ "YYYY-MM-DDTHH:MM:SS"）。月フィルタが前方一致のため
  scheduled_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  status: MeetingStatus;
  final_minutes: string | null;
  batch_model: string | null;
  generation_seconds: number | null;
  audio_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface Participant {
  id: string;
  meeting_id: string;
  name: string;
  role: string | null;
  voice_hint: string | null;
  sort_order: number | null;
}

export interface TimelineElement {
  id: string;
  meeting_id: string;
  seq: number;
  kind: "ai_transcription" | "human_memo";
  speaker_id: number | null;
  t_ms: number;
  text_raw: string;
  text_refined: string | null;
  is_refined: boolean;
  created_at: string;
}

export interface MeetingDetail {
  meeting: Meeting;
  participants: Participant[];
  timeline: TimelineElement[];
}

/** 指定年月の会議一覧（scheduled_start 昇順）。month は 1-12。 */
export const listMeetings = (year: number, month: number): Promise<Meeting[]> =>
  invoke<Meeting[]>("list_meetings", { year, month });

/** 会議＋参加者＋（任意で）元タイムラインを保存。id・各時刻は呼び出し側で確定して渡す。 */
export const createMeeting = (
  meeting: Meeting,
  participants: Participant[],
  timeline: TimelineElement[] = [],
): Promise<void> => invoke<void>("create_meeting", { meeting, participants, timeline });

/** 会議1件の詳細（本体＋参加者＋タイムライン）。無ければ null。 */
export const getMeetingDetail = (id: string): Promise<MeetingDetail | null> =>
  invoke<MeetingDetail | null>("get_meeting_detail", { id });

/** 確認用デモデータ投入（dev のみ・冪等）。当月の year/month を渡す。 */
export const seedDemo = (year: number, month: number): Promise<void> =>
  invoke<void>("seed_demo", { year, month });

/** ローカルISO8601(無TZ)文字列を生成: "YYYY-MM-DDTHH:MM:SS"。`new Date().toISOString()` はUTC(Z)で
 *  月フィルタ(前方一致)とずれるため、ローカル時刻で手組みする。 */
export const localIso = (d: Date = new Date()): string => {
  const p = (n: number, w = 2): string => String(n).padStart(w, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
};
