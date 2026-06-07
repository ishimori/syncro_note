<script setup lang="ts">
// S-03 議事録詳細（過去会議）— Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-03_minutes-detail.html。
// 「最終議事録（Markdown）＋元タイムライン（折りたたみの証跡）」を表示する。
// 元モックは ?id=... で会議を切替えるが、ここでは左ドロワーの「過去の議事録」
// クリックでローカルに切替える（URL/Tauri/ネットワーク非依存）。
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

const router = useRouter();

interface MinutesSection {
  h: string;
  items: string[];
}
interface TimelineEntry {
  name: string;
  t: string;
  text: string;
  memo: boolean;
}
interface Meeting {
  title: string;
  dateShort: string;
  date: string;
  time: string;
  dur: string;
  place: string;
  participants: string[];
  attachments: string[];
  model: string;
  minutes: MinutesSection[];
  timeline: TimelineEntry[];
}
interface CompletedListItem {
  id: string;
  title: string;
  dateShort: string;
}

const leftDrawer = ref(true);

// 会議ごとの議事録（ダミーデータ）。元モックは S-01 から ?id=... で開く。
const MEETINGS: Record<string, Meeting> = {
  "m-youken": {
    title: "要件レビュー",
    dateShort: "6/3",
    date: "2026/06/03(水)",
    time: "10:00–11:05",
    dur: "1時間5分",
    place: "会議室A",
    participants: ["鈴木（PM）", "佐藤（エンジニア）"],
    attachments: ["FY26_予算案.xlsx"],
    model: "gemma4:26b",
    minutes: [
      {
        h: "■ 会議概要",
        items: ["基本設計書(SSOT)のレビューを実施。リアルタイム整形を真実源にしない方針を確認。"],
      },
      {
        h: "■ 決定事項（誰が・何を・いつまでに）",
        items: [
          "佐藤：話者分離は whisper 非依存（pyannote/sherpa-onnx）で PoC を 6/20 までに。",
          "鈴木：清書モデルを gemma4:26b に確定。所要時間表示は実測 3〜6分に修正。",
        ],
      },
      {
        h: "■ 保留事項・次回の課題",
        items: ["32B密モデルの要否、iGPU部分オフロードは余力検証。"],
      },
      {
        h: "■ アクションアイテム（担当付き）",
        items: ["[ ] DD-004 起票（佐藤）", "[ ] UI文言の修正（鈴木）"],
      },
      {
        h: "■ 各アジェンダの議論詳細",
        items: ["確定テキスト即表示を主役とする設計で、CPUでも実用的なリアルタイム性が成立する見込み。"],
      },
    ],
    timeline: [
      { name: "鈴木（PM）", t: "10:05", text: "来期の予算は基本ラインとして100万円で考えています。", memo: false },
      { name: "📝人間メモ", t: "10:05", text: "★社長から「最大150万まで決済を出す」と口頭指示あり", memo: true },
      { name: "佐藤（エンジニア）", t: "10:06", text: "了解しました。では150万を上限にプロトタイプを進めます。", memo: false },
    ],
  },
  "m-gijutsu": {
    title: "技術選定MTG",
    dateShort: "6/9",
    date: "2026/06/09(火)",
    time: "14:00–14:50",
    dur: "50分",
    place: "オンライン",
    participants: ["鈴木（PM）", "佐藤（エンジニア）", "田中（デザイナー）"],
    attachments: ["製品仕様_v3.pdf"],
    model: "gemma4:26b",
    minutes: [
      {
        h: "■ 会議概要",
        items: ["評価期のスタック（faster-whisper / Ollama+Qwen / sounddevice）を確認し、Phase 0 のベンチ方針を合意。"],
      },
      {
        h: "■ 決定事項（誰が・何を・いつまでに）",
        items: ["佐藤：live=qwen3:8b / batch=gemma4:26b でベンチ継続。", "鈴木：RTF<1 を Phase 0 のゲートに設定。"],
      },
      {
        h: "■ 保留事項・次回の課題",
        items: ["STT併走下の tok/s 劣化（16〜51%）の実測は DD-003 で確定。"],
      },
      {
        h: "■ アクションアイテム（担当付き）",
        items: ["[ ] DD-003 起票（佐藤）", "[ ] 評価指標の表をロードマップへ反映（鈴木）"],
      },
      {
        h: "■ 各アジェンダの議論詳細",
        items: ["CPUのメモリ帯域律速のため、既定は STT↔LLM の時間分離とする。"],
      },
    ],
    timeline: [
      { name: "佐藤（エンジニア）", t: "14:03", text: "8bのTTFTが0.39秒で最速でした。", memo: false },
      { name: "📝人間メモ", t: "14:10", text: "★併走時のtok/s劣化は別途DDで実測する", memo: true },
      { name: "鈴木（PM）", t: "14:12", text: "では時間分離を既定にしましょう。", memo: false },
    ],
  },
  "m-sprint": {
    title: "スプリント計画",
    dateShort: "6/12",
    date: "2026/06/12(金)",
    time: "09:30–10:30",
    dur: "1時間",
    place: "会議室B",
    participants: ["鈴木（PM）", "佐藤（エンジニア）"],
    attachments: [],
    model: "gemma4:26b",
    minutes: [
      { h: "■ 会議概要", items: ["次スプリントの DD候補を棚卸しし、優先度を決定。"] },
      {
        h: "■ 決定事項（誰が・何を・いつまでに）",
        items: ["佐藤：DD-005（liveパイプライン縦切り）を最優先で着手。"],
      },
      {
        h: "■ 保留事項・次回の課題",
        items: ["話者分離PoC（DD-004）はDD-003の結果を見て着手判断。"],
      },
      {
        h: "■ アクションアイテム（担当付き）",
        items: ["[ ] DD-005 着手（佐藤・今スプリント）", "[ ] バックログ整理（鈴木）"],
      },
      {
        h: "■ 各アジェンダの議論詳細",
        items: ["LLM抜きで確定即表示までを先に通し、ドロップ0・キュー有界を確認する方針。"],
      },
    ],
    timeline: [
      { name: "鈴木（PM）", t: "09:35", text: "今スプリントは縦切りを優先しましょう。", memo: false },
      { name: "佐藤（エンジニア）", t: "09:37", text: "了解です。DD-005から着手します。", memo: false },
    ],
  },
  "m-1on1": {
    title: "1on1",
    dateShort: "6/12",
    date: "2026/06/12(金)",
    time: "17:00–17:30",
    dur: "30分",
    place: "会議室C",
    participants: ["鈴木（PM）", "佐藤（エンジニア）"],
    attachments: [],
    model: "gemma4:26b",
    minutes: [
      { h: "■ 会議概要", items: ["進捗の振り返りと負荷状況の確認。"] },
      { h: "■ 決定事項（誰が・何を・いつまでに）", items: ["鈴木：ベンチ環境の整備を支援。"] },
      { h: "■ 保留事項・次回の課題", items: ["なし"] },
      { h: "■ アクションアイテム（担当付き）", items: ["[ ] 来週の予定を共有（鈴木）"] },
      {
        h: "■ 各アジェンダの議論詳細",
        items: ["ローカルLLM開発は初挑戦のため、段階的に進める方針を再確認。"],
      },
    ],
    timeline: [{ name: "📝人間メモ", t: "17:05", text: "★負荷は許容範囲。来週も同ペースで", memo: true }],
  },
};

// 既定の会議。左ドロワーの「過去の議事録」クリックでローカルに切替える。
const selectedId = ref<string>("m-youken");
const found = computed<boolean>(() => selectedId.value in MEETINGS);
const id = computed<string>(() => (found.value ? selectedId.value : "m-youken"));
const mtg = computed<Meeting>(() => MEETINGS[id.value] as Meeting);

const completedList = computed<CompletedListItem[]>(() =>
  Object.entries(MEETINGS).map(([k, v]) => ({ id: k, title: v.title, dateShort: v.dateShort })),
);

const selectMeeting = (mid: string): void => {
  selectedId.value = mid;
};

// Markdownコピー / エクスポートは見た目のみ（実I/Oなし）。
const copyMarkdown = (): void => {
  /* visual only: clipboard I/O は Phase 3 */
};
const exportMinutes = (): void => {
  /* visual only: file I/O は Phase 3 */
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 戻る・状態バッジ・Markdownコピー / エクスポート -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="arrow_back" @click="router.push('/s01')">
          <q-tooltip>カレンダーへ戻る</q-tooltip>
        </q-btn>
        <q-toolbar-title>議事録詳細</q-toolbar-title>
        <q-badge color="green-6" label="completed" class="q-mr-sm" />
        <q-btn flat dense no-caps icon="content_copy" label="Markdownコピー" @click="copyMarkdown" />
        <q-btn flat dense no-caps icon="download" label="エクスポート" @click="exportMinutes" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 960px; margin: 0 auto">
        <q-banner v-if="!found" class="bg-orange-2 q-mb-md" rounded>
          <template v-slot:avatar><q-icon name="warning" color="orange-9" /></template>
          指定の会議（id={{ id }}）が見つかりません。既定の議事録を表示しています。
        </q-banner>

        <!-- 過去の議事録（completed）: 元モックの左ドロワー一覧をローカル切替に変換 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section class="row items-center q-pb-none">
            <div class="text-subtitle2 text-grey-7">
              <q-icon name="check_circle" color="green-6" class="q-mr-xs" />過去の議事録（completed）
            </div>
          </q-card-section>
          <q-card-section class="row q-gutter-xs">
            <q-chip
              v-for="m in completedList"
              :key="m.id"
              clickable
              :color="m.id === id ? 'green-6' : 'grey-3'"
              :text-color="m.id === id ? 'white' : 'dark'"
              icon="description"
              @click="selectMeeting(m.id)"
            >
              {{ m.title }}
              <span class="q-ml-xs text-caption">{{ m.dateShort }}</span>
            </q-chip>
          </q-card-section>
        </q-card>

        <!-- メタ -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-h6">{{ mtg.title }}</div>
            <div class="text-grey-7 q-mt-xs">
              {{ mtg.date }} {{ mtg.time }} ・ {{ mtg.place }} ・ 所要 {{ mtg.dur }}
            </div>
            <div class="q-mt-sm row q-gutter-xs">
              <q-chip v-for="p in mtg.participants" :key="p" dense icon="person" :label="p" />
              <q-chip v-for="a in mtg.attachments" :key="a" dense icon="attach_file" :label="a" />
            </div>
          </q-card-section>
        </q-card>

        <!-- 最終議事録 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section class="row items-center">
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="description" class="q-mr-xs" />最終議事録
            </div>
            <q-space />
            <q-badge outline color="grey-7" :label="'batch: ' + mtg.model" />
          </q-card-section>
          <q-separator />
          <q-card-section class="md">
            <template v-for="(sec, si) in mtg.minutes" :key="si">
              <h2>{{ sec.h }}</h2>
              <ul>
                <li v-for="(it, ii) in sec.items" :key="ii">{{ it }}</li>
              </ul>
            </template>
          </q-card-section>
        </q-card>

        <!-- 元タイムライン（折りたたみ） -->
        <q-card flat bordered>
          <q-expansion-item icon="forum" label="元タイムライン（証跡）" caption="確定文字起こし＋人間メモ">
            <q-separator />
            <q-card-section>
              <q-chat-message
                v-for="(e, ei) in mtg.timeline"
                :key="ei"
                :name="e.name"
                :text="[e.text]"
                :stamp="e.t"
                :sent="e.memo"
                :bg-color="e.memo ? 'orange-2' : 'grey-2'"
              />
            </q-card-section>
          </q-expansion-item>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.md h2 {
  font-size: 1.1rem;
  margin: 1.1em 0 0.4em;
  border-left: 4px solid var(--q-primary);
  padding-left: 0.5em;
}
.md ul {
  margin: 0.2em 0 0.8em 1.2em;
}
.md li {
  margin: 0.2em 0;
}
</style>
