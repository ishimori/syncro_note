// S-05 → S-06 → S-07 の縦串で共有する「清書セッション」状態（DD-012-2 Phase 2）。
// 画面間はルーターのみで状態を持たないため、軽量な reactive シングルトンで受け渡す
// （Pinia 等は未導入。会議1本ぶんの一時状態なのでこれで十分）。
import { reactive } from "vue";

/** 証跡として保存する元タイムライン1行（S-03 詳細で表示）。DBの timeline_elements に対応。 */
export interface TimelineRow {
  kind: "ai_transcription" | "human_memo";
  speakerId: number | null; // 話者分離は未実装のため当面 null
  tMs: number; // 会議開始からの相対ミリ秒
  text: string; // 確定原文 or メモ本文
}

export interface MinutesSession {
  title: string; // 会議名（清書プロンプトの前提に渡す）
  transcript: string; // 清書元（確定テキスト＋人間メモ・gemmaへ渡す連結文字列）
  timeline: TimelineRow[]; // 証跡（保存時に timeline_elements として書き込む構造化データ）
  finalMarkdown: string; // 清書結果（summary-done のMarkdown・正規化済み）
  batchModel: string | null; // 清書に使ったモデル名（summary-meta）
  generationSeconds: number | null; // 清書所要秒（summary-done の eval_s）
}

export const minutesSession = reactive<MinutesSession>({
  title: "",
  transcript: "",
  timeline: [],
  finalMarkdown: "",
  batchModel: null,
  generationSeconds: null,
});

/** 保存完了後などにセッションを空に戻す（次の会議へ持ち越さない）。 */
export const resetMinutesSession = (): void => {
  minutesSession.title = "";
  minutesSession.transcript = "";
  minutesSession.timeline = [];
  minutesSession.finalMarkdown = "";
  minutesSession.batchModel = null;
  minutesSession.generationSeconds = null;
};
