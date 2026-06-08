<script setup lang="ts">
// 会話ログ（元タイムライン）の共通表示部品。S-03（過去詳細）/S-06（生成中）/S-07（プレビュー）で使い回す。
// 確定文字起こし＋人間メモを、話者ごとの淡色気泡＋相対タイムスタンプで描画する（DD-012-11 と同じ色規則）。
// データ源は画面ごとに違う（DBの timeline_elements / セッションの TimelineRow）ため、
// 呼び出し側で {speakerId,tMs,text,kind} の最小形に正規化して渡す（下記 LogItem / LogSpeaker）。
import { computed } from "vue";

interface LogItem {
  kind: "ai_transcription" | "human_memo" | string;
  speakerId: number | null; // 話者番号。話者分離なし/人間メモは null
  tMs: number; // 会議開始からの相対ミリ秒
  text: string; // 確定原文 or メモ本文
}
interface LogSpeaker {
  speakerId: number;
  confirmedName: string | null; // 確定名（無ければ「話者 n」表示）
}

const props = defineProps<{ items: LogItem[]; speakers?: LogSpeaker[] }>();

// 本文が空（時刻だけ）の行は表示しない。模擬AI/無音などで空の確定行が混ざることがあるため。
const rows = computed<LogItem[]>(() => props.items.filter((e) => e.text?.trim()));

const msToStamp = (ms: number): string => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

// 話者番号→確定名（speaker_mappings 由来）。未確定は「話者 n」。
const speakerNames = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {};
  for (const s of props.speakers ?? []) if (s.confirmedName) map[s.speakerId] = s.confirmedName;
  return map;
});

const speakerName = (e: LogItem): string => {
  if (e.kind === "human_memo") return "📝人間メモ";
  if (e.speakerId === null) return "話者 ?";
  return speakerNames.value[e.speakerId] ?? `話者 ${e.speakerId}`;
};

// 話者ごとの淡い背景色（S-05/S-03 と同じ番号→色の規則）。
const BUBBLE_COLORS = [
  "blue-2",
  "deep-orange-2",
  "green-2",
  "purple-2",
  "teal-2",
  "pink-2",
  "indigo-2",
  "brown-3",
];
const bubbleColor = (e: LogItem): string => {
  if (e.kind === "human_memo") return "orange-2";
  if (e.speakerId === null) return "grey-2";
  return BUBBLE_COLORS[e.speakerId % BUBBLE_COLORS.length];
};
</script>

<template>
  <div v-if="rows.length === 0" class="text-grey-6 text-caption">会話ログはありません。</div>
  <q-chat-message
    v-for="(e, i) in rows"
    :key="i"
    :name="speakerName(e)"
    :text="[e.text]"
    :stamp="msToStamp(e.tMs)"
    :sent="e.kind === 'human_memo'"
    :bg-color="bubbleColor(e)"
  />
</template>
