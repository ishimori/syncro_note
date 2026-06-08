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

/** 話者番号→名前の対応（DBの speaker_mappings に対応・DD-012-11）。
 *  表示名導出: confirmed_name ?? ai_guess_name ?? `Speaker_${speaker_id}`。 */
export interface SpeakerMapping {
  meeting_id: string;
  speaker_id: number;
  confirmed_name: string | null;
  ai_guess_name: string | null;
  confirmed_participant_id: string | null;
  updated_at: string;
}

export interface MeetingDetail {
  meeting: Meeting;
  participants: Participant[];
  timeline: TimelineElement[];
  speaker_mappings: SpeakerMapping[];
  vocab: string[]; // 専門用語（DD-012-12 Bug#7）
}

/** 指定年月の会議一覧（scheduled_start 昇順）。month は 1-12。 */
export const listMeetings = (year: number, month: number): Promise<Meeting[]> =>
  invoke<Meeting[]>("list_meetings", { year, month });

/** 会議＋参加者＋（任意で）元タイムライン・話者マッピングを保存。id・各時刻は呼び出し側で確定して渡す。 */
export const createMeeting = (
  meeting: Meeting,
  participants: Participant[],
  timeline: TimelineElement[] = [],
  speakerMappings: SpeakerMapping[] = [],
  vocab: string[] = [],
): Promise<void> =>
  invoke<void>("create_meeting", { meeting, participants, timeline, speakerMappings, vocab });

/** 会議1件の詳細（本体＋参加者＋タイムライン）。無ければ null。 */
export const getMeetingDetail = (id: string): Promise<MeetingDetail | null> =>
  invoke<MeetingDetail | null>("get_meeting_detail", { id });

/** 開いていた予定に録音を紐づけて「完了」保存（S-07）。予定日・タイトルは保持し、status='completed'・
 *  議事録本文・モデル情報を書き戻す。タイムラインは全入替（delete→insert）。時刻・idは呼び出し側で確定して渡す。 */
export const completeMeeting = (
  id: string,
  finalMinutes: string,
  batchModel: string | null,
  generationSeconds: number | null,
  updatedAt: string,
  timeline: TimelineElement[],
  speakerMappings: SpeakerMapping[] = [],
): Promise<void> =>
  invoke<void>("complete_meeting", {
    id,
    finalMinutes,
    batchModel,
    generationSeconds,
    updatedAt,
    timeline,
    speakerMappings,
  });

/** 会議を1件削除（DD-012-9）。参加者・タイムライン・添付・用語は CASCADE で連動削除。 */
export const deleteMeeting = (id: string): Promise<void> =>
  invoke<void>("delete_meeting", { id });

/** 予定日時のみ更新（S-01 ドラッグ移動 / DD-012-9）。end は無ければ null。時刻維持は呼び出し側で確定。 */
export const updateMeetingSchedule = (
  id: string,
  scheduledStart: string,
  scheduledEnd: string | null,
  updatedAt: string,
): Promise<void> =>
  invoke<void>("update_meeting_schedule", { id, scheduledStart, scheduledEnd, updatedAt });

/** 会議の編集（S-02 編集モード / DD-012-9）。会議行を更新。`participants`/`vocab` 省略時はそれぞれ
 *  触れない（完了会議の話者リンク保全用）。渡した場合は全入替（DD-012-12 Bug#7: vocab を追加）。 */
export const updateMeeting = (
  meeting: Meeting,
  participants?: Participant[],
  vocab?: string[],
): Promise<void> =>
  invoke<void>("update_meeting", {
    meeting,
    participants: participants ?? null,
    vocab: vocab ?? null,
  });

export type ParseStatus = "pending" | "done" | "error";

export interface Attachment {
  id: string;
  meeting_id: string;
  file_name: string;
  local_path: string;
  file_type: "xlsx" | "pdf";
  extracted_text: string | null;
  parse_status: ParseStatus;
  created_at: string;
}

/** 事前資料を取り込む（S-02 / DD-012-10）。元ファイルをアプリ内へコピー→抽出→done/error を反映した
 *  確定後の行を返す（抽出はサイドカーで完結＝完全オフライン）。id・created_at は呼び出し側で確定して渡す。 */
export const addAttachment = (
  id: string,
  meetingId: string,
  srcPath: string,
  fileName: string,
  fileType: "xlsx" | "pdf",
  createdAt: string,
): Promise<Attachment> =>
  invoke<Attachment>("add_attachment", {
    id,
    meetingId,
    srcPath,
    fileName,
    fileType,
    createdAt,
  });

/** 会議の添付一覧（created_at 昇順 / S-02・S-03）。 */
export const listAttachments = (meetingId: string): Promise<Attachment[]> =>
  invoke<Attachment[]>("list_attachments", { meetingId });

/** 添付を1件削除（行＋コピー済みファイル / DD-012-10）。 */
export const removeAttachment = (id: string): Promise<void> =>
  invoke<void>("remove_attachment", { id });

/** カレンダー予定のコピペ取込結果（DD-012-13）。LLM が構造化した会議下書き。
 *  `scheduled_start`/`end` はローカルISO8601(無TZ)。日時が読み取れなければ null。
 *  `year_inferred`＝年がテキストに無くシステム年で補完した（UIは「要確認」表示にする）。 */
export interface ParsedMeetingDraft {
  title: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  place: string;
  agenda: string;
  participants: { name: string; role: string }[];
  year_inferred: boolean;
}

/** カレンダーからコピペした予定テキストを qwen で構造化する（DD-012-13・完全オフライン）。
 *  サイドカーをブロッキング実行して draft を1個返す。S-02 フォームへ流し込む用途。 */
export const parseCalendarText = (text: string): Promise<ParsedMeetingDraft> =>
  invoke<ParsedMeetingDraft>("parse_calendar_text", { text });

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
