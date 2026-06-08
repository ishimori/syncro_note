// DD-013-1: 模擬AI（dev専用）。実録音(Rust whisper)を待たずに「AIが自動で文字起こしを追記し続ける」
// 状況を再現し、人間メモ入力との同時編集を Playwright で検証できるようにする。
// 実 token 流入は DD-014-4 で差し替える（本ファイルは検証用の固定台本＋遅延）。

export interface MockAiSegment {
  seq: number;
  speaker: string;
  text: string;
}

// 同時編集の検証に十分な長さ（巡回1周で約120字 × 数周で500字超）になる固定台本。
const SCRIPT: ReadonlyArray<{ speaker: string; text: string }> = [
  { speaker: "spk0", text: "本日の定例を始めます。まず先週の進捗から共有します。" },
  { speaker: "spk1", text: "認識基盤の検証が終わり、同時編集の土台に着手しました。" },
  { speaker: "spk0", text: "了解です。リスクの高いところから順に潰していきましょう。" },
  { speaker: "spk1", text: "はい。五百字規模の連続編集でも壊れないことを自動テストで担保します。" },
  { speaker: "spk0", text: "では左の文字起こしを右のメモへ送る操作感も確認しましょう。" },
];

/**
 * 模擬AIを開始。intervalMs ごとに onSegment を呼び、台本を巡回して追記し続ける。
 * 返り値の stop() で停止。
 */
export function startMockAi(
  onSegment: (seg: MockAiSegment) => void,
  intervalMs = 1500,
): () => void {
  let seq = 0;
  const timer = setInterval(() => {
    const line = SCRIPT[seq % SCRIPT.length];
    onSegment({ seq, speaker: line.speaker, text: line.text });
    seq++;
  }, intervalMs);
  return () => clearInterval(timer);
}
