// S-05 → S-06 → S-07 の縦串で共有する「清書セッション」状態（DD-012-2 Phase 2）。
// 画面間はルーターのみで状態を持たないため、軽量な reactive シングルトンで受け渡す
// （Pinia 等は未導入。会議1本ぶんの一時状態なのでこれで十分）。
import { reactive } from "vue";

/** 証跡として保存する元タイムライン1行（S-03 詳細で表示）。DBの timeline_elements に対応。 */
export interface TimelineRow {
  kind: "ai_transcription" | "human_memo";
  speakerId: number | null; // 話者番号（spk0→0）。話者分離なし/人間メモは null（DD-012-5/11）
  tMs: number; // 会議開始からの相対ミリ秒
  text: string; // 確定原文 or メモ本文
}

/** 話者番号→確定名（S-03 表示名解決・色分け用）。DBの speaker_mappings に対応（DD-012-11）。
 *  保存時に S-07 が meeting_id を付けて SpeakerMapping へ変換する。 */
export interface SpeakerRow {
  speakerId: number; // 会議内の話者番号
  confirmedName: string | null; // 人間が確定した名前（未確定は null＝S-03 で Speaker_n 表示）
}

/** 録音中に右パネルで編集する参加者（名前＋役職）。保存時 participants へ変換（DD-016-3）。 */
export interface SessionParticipant {
  name: string;
  role: string; // 役職（任意・空文字可）
}

export interface MinutesSession {
  title: string; // 会議名（清書プロンプトの前提に渡す）
  // 紐づく既存予定のid。カレンダー(S-01)で予定を開いて録音した場合に S-05 が設定し、保存(S-07)で
  // その予定を「完了」へ書き戻す（予定日・タイトルを保持）。開かずにその場で録音した場合は null＝今日の新規会議を作成。
  // DD-016-3/案C: ad-hoc で事前資料を追加すると仮会議を作り、その id をここに入れる（isTempMeeting=true）。
  meetingId: string | null;
  // ad-hoc 仮会議か（DD-016-3）。true のとき S-06/清書中の中断で仮会議を削除する（保存前の幽霊を残さない）。
  isTempMeeting: boolean;
  // 録音中に右パネルで編集したアジェンダ・参加者（ad-hoc 保存時に会議へ反映）DD-016-3。
  agenda: string;
  participants: SessionParticipant[];
  transcript: string; // 清書元（確定テキスト＋人間メモ・gemmaへ渡す連結文字列）
  timeline: TimelineRow[]; // 証跡（保存時に timeline_elements として書き込む構造化データ）
  speakers: SpeakerRow[]; // 話者番号→確定名（保存時に speaker_mappings へ・DD-012-11）
  finalMarkdown: string; // 清書結果（summary-done のMarkdown・正規化済み）
  batchModel: string | null; // 清書に使ったモデル名（summary-meta）
  generationSeconds: number | null; // 清書所要秒（summary-done の eval_s）
}

export const minutesSession = reactive<MinutesSession>({
  title: "",
  meetingId: null,
  isTempMeeting: false,
  agenda: "",
  participants: [],
  transcript: "",
  timeline: [],
  speakers: [],
  finalMarkdown: "",
  batchModel: null,
  generationSeconds: null,
});

/** 保存完了後などにセッションを空に戻す（次の会議へ持ち越さない）。 */
export const resetMinutesSession = (): void => {
  minutesSession.title = "";
  minutesSession.meetingId = null;
  minutesSession.isTempMeeting = false;
  minutesSession.agenda = "";
  minutesSession.participants = [];
  minutesSession.transcript = "";
  minutesSession.timeline = [];
  minutesSession.speakers = [];
  minutesSession.finalMarkdown = "";
  minutesSession.batchModel = null;
  minutesSession.generationSeconds = null;
};
