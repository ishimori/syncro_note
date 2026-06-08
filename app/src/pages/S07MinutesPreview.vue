<script setup lang="ts">
// S-07 議事録プレビュー（清書完了）— DD-012-2 Phase 2: 実データ結線。
// S-06 から渡された清書Markdown(minutesSession)を表示し、編集トグルでソース編集に切替える。
// 「保存」で初めて DB に書く → カレンダー(S-01)へ。予定を開いて録音した場合(minutesSession.meetingId 有)は
// complete_meeting でその予定を「完了」へ書き戻し（予定日・タイトル保持）、それ以外は create_meeting で今日の新規会議を作成。
// 未保存ではDBに何も残さない＝中断/離脱で「生成中」の幽霊会議を作らない設計。
// 注意: invoke は実ウィンドウ(Tauri)専用。素ブラウザ(Playwright)では保存できない。
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";
import ActiveRecordChip from "../components/ActiveRecordChip.vue";
import { minutesSession, resetMinutesSession } from "../session";
import {
  completeMeeting,
  createMeeting,
  localIso,
  type Meeting,
  type SpeakerMapping,
  type TimelineElement,
} from "../api";
import { setActive } from "../title";

const router = useRouter();
const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const leftDrawer = ref(true);
const editMode = ref(false);
const src = ref(minutesSession.finalMarkdown); // 編集可能コピー（保存対象）
const title = minutesSession.title || "議事録";
const model = minutesSession.batchModel;
const seconds = minutesSession.generationSeconds;
const saving = ref(false);
const saveError = ref("");

// OSウィンドウのタイトルに保存対象の議事録名を出す（直接遷移でセッションが空なら画面名のまま）。
if (minutesSession.title) setActive({ screen: "議事録プレビュー", name: minutesSession.title });

// 清書結果があれば保存・表示できる（直接遷移などは案内に切替）。
const hasData = computed(() => !!minutesSession.finalMarkdown);

// 最小Markdownレンダラ（## 見出し / - 箇条書き / - [ ] チェック / 段落）。清書の固定3節向け。
// v-html を使わず（XSS安全）、ブロック配列にして v-for で描画する。未知行は段落で安全に流す。
interface Block {
  kind: "h2" | "h3" | "p" | "ul";
  text?: string;
  items?: { text: string; checked: boolean | null }[];
}
const blocks = computed<Block[]>(() => {
  const out: Block[] = [];
  let ul: { text: string; checked: boolean | null }[] | null = null;
  const flush = (): void => {
    if (ul) {
      out.push({ kind: "ul", items: ul });
      ul = null;
    }
  };
  for (const raw of src.value.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (line.startsWith("### ")) {
      flush();
      out.push({ kind: "h3", text: line.slice(4) });
    } else if (line.startsWith("## ")) {
      flush();
      out.push({ kind: "h2", text: line.slice(3) });
    } else if (line.startsWith("# ")) {
      flush();
      out.push({ kind: "h2", text: line.slice(2) });
    } else if (bullet) {
      const task = bullet[1].match(/^\[( |x|X)\]\s*(.*)$/);
      ul = ul ?? [];
      if (task) ul.push({ text: task[2], checked: task[1].toLowerCase() === "x" });
      else ul.push({ text: bullet[1], checked: null });
    } else if (line.trim() === "") {
      flush();
    } else {
      flush();
      out.push({ kind: "p", text: line });
    }
  }
  flush();
  return out;
});

const save = async (): Promise<void> => {
  if (!isTauri || saving.value || !minutesSession.finalMarkdown) return;
  saving.value = true;
  saveError.value = "";
  try {
    const now = localIso();
    // 証跡（元タイムライン）を保存先の meeting_id 付きで構造化する（S-03 詳細で表示される）。
    const buildTimeline = (meetingId: string): TimelineElement[] =>
      minutesSession.timeline.map((it, i) => ({
        id: crypto.randomUUID(),
        meeting_id: meetingId,
        seq: i,
        kind: it.kind,
        speaker_id: it.speakerId,
        t_ms: it.tMs,
        text_raw: it.text,
        text_refined: null,
        is_refined: false,
        created_at: now,
      }));
    // 話者番号→確定名を speaker_mappings として保存（S-03 で表示名解決＋色分け・DD-012-11）。
    const buildSpeakers = (meetingId: string): SpeakerMapping[] =>
      minutesSession.speakers.map((s) => ({
        meeting_id: meetingId,
        speaker_id: s.speakerId,
        confirmed_name: s.confirmedName,
        ai_guess_name: null,
        confirmed_participant_id: null,
        updated_at: now,
      }));

    if (minutesSession.meetingId) {
      // 予定を開いて録音した: その予定を「完了」へ書き戻す（予定日・タイトルは保持＝今日へずらさない）。
      const linkedId = minutesSession.meetingId;
      await completeMeeting(
        linkedId,
        src.value,
        minutesSession.batchModel,
        minutesSession.generationSeconds,
        now, // updated_at（予定日 scheduled_start は保持＝今日へずらさない）
        buildTimeline(linkedId),
        buildSpeakers(linkedId),
      );
    } else {
      // 予定を開かずその場で録音した: 今日の新規会議を「完了」で1件作成する（従来どおり）。
      const id = crypto.randomUUID();
      const meeting: Meeting = {
        id,
        title: minutesSession.title || "議事録",
        agenda: null,
        place: null,
        scheduled_start: now,
        scheduled_end: null,
        actual_start: now,
        actual_end: now,
        status: "completed",
        final_minutes: src.value,
        batch_model: minutesSession.batchModel,
        generation_seconds: minutesSession.generationSeconds,
        audio_path: null,
        created_at: now,
        updated_at: now,
      };
      await createMeeting(meeting, [], buildTimeline(id), buildSpeakers(id));
    }
    resetMinutesSession();
    router.push("/s01");
  } catch (e) {
    saveError.value = String(e);
    saving.value = false;
  }
};

const copy = async (): Promise<void> => {
  try {
    await navigator.clipboard.writeText(src.value);
  } catch {
    /* 一部環境でクリップボード不可。無視 */
  }
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 編集トグル・コピー・保存 -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-icon name="fact_check" size="24px" class="q-mr-sm" />
        <q-toolbar-title>議事録プレビュー（清書完了）</q-toolbar-title>
        <ActiveRecordChip />
        <q-toggle
          v-if="hasData"
          v-model="editMode"
          color="white"
          keep-color
          label="編集"
          left-label
          class="q-mr-md"
        />
        <q-btn v-if="hasData" flat dense no-caps icon="content_copy" label="コピー" @click="copy" />
        <q-btn
          v-if="hasData"
          unelevated
          no-caps
          color="green-6"
          icon="save"
          :loading="saving"
          :disable="!isTauri || saving"
          label="保存（completed）"
          class="q-ml-sm"
          @click="save"
        >
          <q-tooltip v-if="!isTauri">実ウィンドウ（Tauri）でのみ保存できます</q-tooltip>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 960px; margin: 0 auto">
        <!-- データなし（直接遷移など） -->
        <q-banner v-if="!hasData" rounded class="bg-amber-2 text-grey-9">
          <template v-slot:avatar><q-icon name="info" color="amber-8" /></template>
          表示する議事録がありません。録音 → 会議を終了 → 清書 の順で進めてください。
          <template v-slot:action>
            <q-btn flat no-caps color="primary" label="カレンダーへ" @click="router.push('/s01')" />
          </template>
        </q-banner>

        <template v-else>
          <q-banner dense rounded class="bg-green-1 q-mb-md text-grey-9">
            <template v-slot:avatar><q-icon name="check_circle" color="green-6" /></template>
            清書が完了しました（{{ model || "—" }}<span v-if="seconds">・所要 {{ seconds }} 秒</span
            >）。内容を確認し、必要なら微修正して保存してください。保存で
            <code>final_minutes</code> 更新・<code>status='completed'</code>。
          </q-banner>

          <q-banner v-if="saveError" dense rounded class="bg-red-2 q-mb-md text-red-10">
            <template v-slot:avatar><q-icon name="error" color="red-7" /></template>
            保存に失敗しました: {{ saveError }}
          </q-banner>

          <q-card flat bordered>
            <q-card-section class="row items-center">
              <div class="text-h6">{{ title }}</div>
            </q-card-section>
            <q-separator />

            <!-- 編集モード: Markdownソース / 表示モード: レンダリング -->
            <q-card-section v-if="editMode">
              <q-input
                type="textarea"
                outlined
                v-model="src"
                autogrow
                input-style="min-height:340px;font-family:ui-monospace,monospace"
              />
            </q-card-section>
            <q-card-section v-else class="md">
              <template v-for="(b, i) in blocks" :key="i">
                <h2 v-if="b.kind === 'h2'">{{ b.text }}</h2>
                <h3 v-else-if="b.kind === 'h3'">{{ b.text }}</h3>
                <ul v-else-if="b.kind === 'ul'">
                  <li v-for="(it, j) in b.items" :key="j">
                    <q-checkbox
                      v-if="it.checked !== null"
                      :model-value="it.checked"
                      disable
                      dense
                      size="xs"
                      class="q-mr-xs"
                    />{{ it.text }}
                  </li>
                </ul>
                <p v-else>{{ b.text }}</p>
              </template>
            </q-card-section>
          </q-card>

          <div class="row q-gutter-sm justify-end q-mt-md q-mb-xl">
            <q-btn flat no-caps label="カレンダーへ戻る" icon="arrow_back" @click="router.push('/s01')" />
            <q-btn
              unelevated
              no-caps
              color="green-6"
              icon="save"
              :loading="saving"
              :disable="!isTauri || saving"
              label="保存して完了"
              @click="save"
            />
          </div>
        </template>
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
.md h3 {
  font-size: 1rem;
  margin: 0.9em 0 0.3em;
  color: #475569;
}
.md ul {
  margin: 0.2em 0 0.8em 1.2em;
}
.md li {
  margin: 0.25em 0;
}
.md p {
  margin: 0.4em 0;
}
</style>
