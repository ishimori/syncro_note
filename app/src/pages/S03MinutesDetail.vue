<script setup lang="ts">
// S-03 議事録詳細（過去会議）— DD-012-3 Phase 2: SQLite 実データ表示。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-03_minutes-detail.html。
// 「最終議事録（final_minutes の Markdown）＋元タイムライン（timeline_elements）」を表示する。
// S-01 から ?id=... で開く。左カードの completed 一覧クリックでローカル切替。
//   注意: invoke は Tauri ランタイム上でのみ動く（素のブラウザ/Playwright では不可）。
import { ref, computed, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useQuasar } from "quasar";
import AppNav from "../components/AppNav.vue";
import {
  listMeetings,
  getMeetingDetail,
  listAttachments,
  type MeetingDetail,
  type Meeting,
  type Attachment,
} from "../api";

const router = useRouter();
const route = useRoute();
const $q = useQuasar();

const leftDrawer = ref(true);
const completed = ref<Meeting[]>([]); // 過去の議事録一覧（completed）
const detail = ref<MeetingDetail | null>(null);
const attachments = ref<Attachment[]>([]); // 事前資料（DD-012-10）
const selectedId = ref<string>("");
const loading = ref(false);
const errorMsg = ref("");

const today = new Date();

// 当月の completed 会議を一覧に（シード/実データ）。
const loadList = async (): Promise<void> => {
  try {
    const all = await listMeetings(today.getFullYear(), today.getMonth() + 1);
    completed.value = all.filter((m) => m.status === "completed");
  } catch (e) {
    errorMsg.value = String(e);
  }
};

const loadDetail = async (id: string): Promise<void> => {
  if (!id) {
    detail.value = null;
    return;
  }
  loading.value = true;
  errorMsg.value = "";
  try {
    detail.value = await getMeetingDetail(id);
    selectedId.value = id;
    attachments.value = detail.value ? await listAttachments(id) : [];
  } catch (e) {
    errorMsg.value = String(e);
    detail.value = null;
    attachments.value = [];
  } finally {
    loading.value = false;
  }
};

onMounted(async () => {
  await loadList();
  const qid = typeof route.query.id === "string" ? route.query.id : "";
  const first = completed.value[0]?.id ?? "";
  await loadDetail(qid || first);
});

const selectMeeting = (id: string): void => {
  void loadDetail(id);
};

// 表示ヘルパ
const dateLabel = (iso: string): string => (iso ? iso.slice(0, 10).replace(/-/g, "/") : "");
const dateShort = (iso: string): string => {
  const m = iso.slice(5, 7).replace(/^0/, "");
  const d = iso.slice(8, 10).replace(/^0/, "");
  return iso ? `${m}/${d}` : "";
};
const timeRange = (m: Meeting): string => {
  const s = m.scheduled_start.slice(11, 16);
  const e = m.scheduled_end ? m.scheduled_end.slice(11, 16) : "";
  return e ? `${s}–${e}` : s;
};
const msToStamp = (ms: number): string => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

// final_minutes(Markdown文字列) を軽量レンダリング: "## 見出し" と "- 箇条書き" を解釈。
interface Block {
  type: "h2" | "ul" | "p";
  text?: string;
  items?: string[];
}
const minutesBlocks = computed<Block[]>(() => {
  const md = detail.value?.meeting.final_minutes ?? "";
  const blocks: Block[] = [];
  let ul: string[] | null = null;
  const flush = (): void => {
    if (ul && ul.length) blocks.push({ type: "ul", items: ul });
    ul = null;
  };
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) {
      flush();
    } else if (line.startsWith("## ")) {
      flush();
      blocks.push({ type: "h2", text: line.slice(3) });
    } else if (line.startsWith("- ")) {
      (ul ||= []).push(line.slice(2));
    } else {
      flush();
      blocks.push({ type: "p", text: line });
    }
  }
  flush();
  return blocks;
});

const participantsLabel = computed<string[]>(() =>
  (detail.value?.participants ?? []).map((p) => (p.role ? `${p.name}（${p.role}）` : p.name)),
);

const speakerName = (e: { kind: string; speaker_id: number | null }): string =>
  e.kind === "human_memo" ? "📝人間メモ" : `話者 ${e.speaker_id ?? "?"}`;

// 添付の表示ヘルパ（DD-012-10）。
const attachIcon = (type: string): string => (type === "xlsx" ? "grid_on" : "picture_as_pdf");
const attachIconColor = (type: string): string => (type === "xlsx" ? "green-7" : "red-7");

// 書き出し（DD-012-9 Phase 4）: 最終議事録(Markdown)をクリップボードへコピー（依存なし）。
const copyMinutes = async (): Promise<void> => {
  const md = detail.value?.meeting.final_minutes ?? "";
  if (!md) {
    $q.notify({ message: "書き出せる議事録がありません", color: "orange-8", icon: "info" });
    return;
  }
  try {
    await navigator.clipboard.writeText(md);
    $q.notify({ message: "議事録をコピーしました", color: "indigo", icon: "content_copy", timeout: 2000 });
  } catch {
    $q.notify({ message: "コピーに失敗しました", color: "negative", icon: "error" });
  }
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 戻る・状態バッジ -->
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
        <q-spinner v-if="loading" color="white" size="20px" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 960px; margin: 0 auto">
        <q-banner v-if="errorMsg" class="bg-orange-2 q-mb-md" rounded>
          <template v-slot:avatar><q-icon name="warning" color="orange-9" /></template>
          読み込みに失敗しました（Tauri ランタイム上で実行していますか？）: {{ errorMsg }}
        </q-banner>

        <!-- 過去の議事録（completed）: クリックでローカル切替 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section class="row items-center q-pb-none">
            <div class="text-subtitle2 text-grey-7">
              <q-icon name="check_circle" color="green-6" class="q-mr-xs" />過去の議事録（completed）
            </div>
          </q-card-section>
          <q-card-section class="row q-gutter-xs">
            <div v-if="completed.length === 0" class="text-grey-6 text-caption">
              当月に完了済みの議事録はありません。
            </div>
            <q-chip
              v-for="m in completed"
              :key="m.id"
              clickable
              :color="m.id === selectedId ? 'green-6' : 'grey-3'"
              :text-color="m.id === selectedId ? 'white' : 'dark'"
              icon="description"
              @click="selectMeeting(m.id)"
            >
              {{ m.title }}
              <span class="q-ml-xs text-caption">{{ dateShort(m.scheduled_start) }}</span>
            </q-chip>
          </q-card-section>
        </q-card>

        <template v-if="detail">
          <!-- メタ -->
          <q-card flat bordered class="q-mb-md">
            <q-card-section>
              <div class="text-h6">{{ detail.meeting.title }}</div>
              <div class="text-grey-7 q-mt-xs">
                {{ dateLabel(detail.meeting.scheduled_start) }} {{ timeRange(detail.meeting) }}
                <span v-if="detail.meeting.place"> ・ {{ detail.meeting.place }}</span>
              </div>
              <div class="q-mt-sm row q-gutter-xs">
                <q-chip v-for="p in participantsLabel" :key="p" dense icon="person" :label="p" />
              </div>
            </q-card-section>
          </q-card>

          <!-- 事前資料（DD-012-10）: 抽出済みは本文プレビュー可 -->
          <q-card v-if="attachments.length" flat bordered class="q-mb-md">
            <q-card-section>
              <div class="text-subtitle1 text-weight-medium">
                <q-icon name="attach_file" class="q-mr-xs" />事前資料
              </div>
            </q-card-section>
            <q-separator />
            <q-list separator>
              <q-expansion-item
                v-for="a in attachments"
                :key="a.id"
                :disable="a.parse_status !== 'done' || !a.extracted_text"
                expand-separator
              >
                <template v-slot:header>
                  <q-item-section avatar>
                    <q-icon :name="attachIcon(a.file_type)" :color="attachIconColor(a.file_type)" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ a.file_name }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-badge v-if="a.parse_status === 'done' && a.extracted_text" color="green-6" label="抽出済み" />
                    <q-badge v-else-if="a.parse_status === 'error'" color="red-6" label="失敗" />
                    <q-badge v-else color="grey-5" label="本文なし" />
                  </q-item-section>
                </template>
                <q-card-section class="bg-grey-1">
                  <pre class="extract-preview">{{ a.extracted_text }}</pre>
                </q-card-section>
              </q-expansion-item>
            </q-list>
          </q-card>

          <!-- 最終議事録 -->
          <q-card flat bordered class="q-mb-md">
            <q-card-section class="row items-center">
              <div class="text-subtitle1 text-weight-medium">
                <q-icon name="description" class="q-mr-xs" />最終議事録
              </div>
              <q-space />
              <q-btn
                flat
                dense
                no-caps
                size="sm"
                icon="content_copy"
                label="コピー"
                color="primary"
                class="q-mr-sm"
                :disable="!detail.meeting.final_minutes"
                @click="copyMinutes"
              />
              <q-badge v-if="detail.meeting.batch_model" outline color="grey-7" :label="'batch: ' + detail.meeting.batch_model" />
            </q-card-section>
            <q-separator />
            <q-card-section class="md">
              <div v-if="!detail.meeting.final_minutes" class="text-grey-6">
                （この会議には清書済み議事録がありません）
              </div>
              <template v-for="(b, bi) in minutesBlocks" :key="bi">
                <h2 v-if="b.type === 'h2'">{{ b.text }}</h2>
                <ul v-else-if="b.type === 'ul'">
                  <li v-for="(it, ii) in b.items" :key="ii">{{ it }}</li>
                </ul>
                <p v-else>{{ b.text }}</p>
              </template>
            </q-card-section>
          </q-card>

          <!-- 元タイムライン（折りたたみ） -->
          <q-card flat bordered>
            <q-expansion-item icon="forum" label="元タイムライン（証跡）" caption="確定文字起こし＋人間メモ">
              <q-separator />
              <q-card-section>
                <div v-if="detail.timeline.length === 0" class="text-grey-6 text-caption">
                  タイムラインはありません。
                </div>
                <q-chat-message
                  v-for="e in detail.timeline"
                  :key="e.id"
                  :name="speakerName(e)"
                  :text="[e.text_raw]"
                  :stamp="msToStamp(e.t_ms)"
                  :sent="e.kind === 'human_memo'"
                  :bg-color="e.kind === 'human_memo' ? 'orange-2' : 'grey-2'"
                />
              </q-card-section>
            </q-expansion-item>
          </q-card>
        </template>

        <q-banner v-else-if="!loading && !errorMsg" class="bg-grey-2 q-mt-md" rounded>
          <template v-slot:avatar><q-icon name="info" color="primary" /></template>
          表示する議事録を上の一覧から選択してください。
        </q-banner>
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
.md p {
  margin: 0.4em 0;
}
.extract-preview {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
  margin: 0;
  font-size: 0.85rem;
  color: #334155;
}
</style>
