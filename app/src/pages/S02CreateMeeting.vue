<script setup lang="ts">
// S-02 会議作成・事前登録 — DD-012-3 で作成→保存、DD-012-9 Phase 4 で編集モードを追加。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-02_create-meeting.html。
// ここで入力した前提（参加者・アジェンダ・用語・資料）が、リアルタイム補正と
// 終了後の清書プロンプトに渡る。本フェーズでは基本情報＋参加者を `meetings`/`participants` に保存する。
//   id・各時刻は frontend で確定して渡す（Rust DB層の純関数設計に合わせる）。
// 編集モード（?id=）: 既存会議を読み込み、`update_meeting` で更新。完了会議は参加者を保護（話者リンク保全）。
// 新規（?date=YYYY-MM-DD）: 空きセルからの遷移で日付を初期化する。
import { ref, reactive, computed, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useQuasar } from "quasar";
import AppNav from "../components/AppNav.vue";
import {
  createMeeting,
  updateMeeting,
  getMeetingDetail,
  localIso,
  type Meeting,
  type Participant as DbParticipant,
} from "../api";

const router = useRouter();
const route = useRoute();
const $q = useQuasar();

interface Participant {
  name: string;
  role: string;
  voice: string;
}

const leftDrawer = ref(true);

// 基本情報（新規の初期値。編集モードでは onMounted で上書きする）
const title = ref("設計レビュー");
const date = ref("2026/06/18");
const start = ref("13:00");
const end = ref("14:00");
const place = ref("会議室A");

// アジェンダ（Markdown可）
const agenda = ref("- 基本設計書のレビュー\n- 話者分離方式の確定\n- 次スプリントのDD候補");

// 参加者リスト
const participants = reactive<Participant[]>([
  { name: "鈴木", role: "PM", voice: "男性・低音" },
  { name: "佐藤", role: "エンジニア", voice: "女性" },
]);
const np = reactive<Participant>({ name: "", role: "", voice: "" });
const addParticipant = (): void => {
  if (np.name) {
    participants.push({ name: np.name, role: np.role, voice: np.voice });
    np.name = "";
    np.role = "";
    np.voice = "";
  }
};
const removeParticipant = (i: number): void => {
  participants.splice(i, 1);
};

// 専門用語辞書
const vocab = ref<string[]>(["Qwen", "Tauri", "SQLite", "SynchroniNote"]);

// 保存処理
const saving = ref(false);
const errorMsg = ref("");

// 編集モード状態
const editingBase = ref<Meeting | null>(null); // 読み込んだ会議（id/status/created_at/清書 等を温存）
const isEditing = computed<boolean>(() => editingBase.value !== null);
// 完了会議は参加者をロック（変更すると timeline_elements.confirmed_participant_id の話者リンクが切れるため）。
const participantsLocked = computed<boolean>(() => editingBase.value?.status === "completed");

// 起動時: ?id= があれば編集モードで読み込み、なければ ?date= で日付を初期化。
onMounted(async () => {
  const id = typeof route.query.id === "string" ? route.query.id : "";
  if (id) {
    try {
      const detail = await getMeetingDetail(id);
      if (!detail) {
        errorMsg.value = "対象の会議が見つかりません（削除済みの可能性があります）";
        return;
      }
      const m = detail.meeting;
      editingBase.value = m;
      title.value = m.title;
      place.value = m.place ?? "";
      agenda.value = m.agenda ?? "";
      date.value = m.scheduled_start.slice(0, 10).replace(/-/g, "/");
      start.value = m.scheduled_start.slice(11, 16);
      end.value = m.scheduled_end ? m.scheduled_end.slice(11, 16) : "";
      participants.splice(
        0,
        participants.length,
        ...detail.participants.map((p) => ({ name: p.name, role: p.role ?? "", voice: p.voice_hint ?? "" })),
      );
    } catch (e) {
      errorMsg.value = String(e);
    }
    return;
  }
  const d = typeof route.query.date === "string" ? route.query.date : "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) date.value = d.replace(/-/g, "/");
});

// "2026/06/18" + "13:00" → ローカルISO "2026-06-18T13:00:00"（月フィルタが前方一致のため無TZ）。
const toIso = (time: string): string | null => {
  const d = date.value.replace(/\//g, "-");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return null;
  const t = /^\d{2}:\d{2}$/.test(time) ? `${time}:00` : "00:00:00";
  return `${d}T${t}`;
};

// 入力 → DB参加者行（編集の全入替・新規の作成で共用）。
const toDbParticipants = (meetingId: string): DbParticipant[] =>
  participants.map((p, i) => ({
    id: crypto.randomUUID(),
    meeting_id: meetingId,
    name: p.name,
    role: p.role || null,
    voice_hint: p.voice || null,
    sort_order: i,
  }));

const save = async (): Promise<void> => {
  if (!title.value) {
    errorMsg.value = "会議名は必須です";
    return;
  }
  const scheduledStart = toIso(start.value);
  if (!scheduledStart) {
    errorMsg.value = "日付は YYYY/MM/DD で入力してください";
    return;
  }
  saving.value = true;
  errorMsg.value = "";
  const editing = editingBase.value !== null;
  try {
    const now = localIso();
    if (editingBase.value) {
      // 編集: 会議行の編集項目だけ上書き（status・final_minutes・実績時刻・created_at は温存）。
      const m: Meeting = {
        ...editingBase.value,
        title: title.value,
        agenda: agenda.value || null,
        place: place.value || null,
        scheduled_start: scheduledStart,
        scheduled_end: toIso(end.value),
        updated_at: now,
      };
      // 完了会議は参加者を保護（undefined＝参加者に触れない）。予定は全入替。
      await updateMeeting(m, participantsLocked.value ? undefined : toDbParticipants(m.id));
    } else {
      const id = crypto.randomUUID();
      const meeting: Meeting = {
        id,
        title: title.value,
        agenda: agenda.value || null,
        place: place.value || null,
        scheduled_start: scheduledStart,
        scheduled_end: toIso(end.value),
        actual_start: null,
        actual_end: null,
        status: "scheduled",
        final_minutes: null,
        batch_model: null,
        generation_seconds: null,
        audio_path: null,
        created_at: now,
        updated_at: now,
      };
      await createMeeting(meeting, toDbParticipants(id));
    }
    // 「どの予定を・いつ」が分かるよう、タイトル＋日付＋時刻を添えて通知する。
    const when = `${date.value} ${start.value}${end.value ? "–" + end.value : ""}`;
    $q.notify({
      message: editing ? "変更を保存しました" : "予定を保存しました",
      caption: `「${title.value}」 ${when}`,
      color: "positive",
      icon: "check_circle",
      timeout: 2500,
    });
    router.push("/s01"); // 保存できたらカレンダーへ（当月なら即表示される）
  } catch (e) {
    errorMsg.value = String(e);
  } finally {
    saving.value = false;
  }
};
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <q-btn flat round dense icon="arrow_back" @click="router.push('/s01')" />
        <q-toolbar-title>{{ isEditing ? "会議の編集" : "会議の作成・事前登録" }}</q-toolbar-title>
        <q-badge :color="isEditing ? 'teal' : 'blue-5'" :label="isEditing ? '編集' : '新規'" />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 820px; margin: 0 auto">
        <q-banner dense rounded class="bg-grey-2 q-mb-md text-grey-8">
          <template v-slot:avatar><q-icon name="lightbulb" color="amber-8" /></template>
          ここで入力した前提（参加者・アジェンダ・用語・資料）が、リアルタイム補正と終了後の清書プロンプトに渡ります。
        </q-banner>

        <!-- 基本情報 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="info" class="q-mr-xs" />基本情報
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-gutter-md">
            <q-input outlined v-model="title" label="会議名 *" :rules="[(v: string) => !!v || '必須']" />
            <div class="row q-col-gutter-md">
              <q-input class="col-12 col-sm-6" outlined v-model="date" label="日付" mask="####/##/##">
                <template v-slot:append><q-icon name="event" /></template>
              </q-input>
              <q-input class="col-6 col-sm-3" outlined v-model="start" label="開始" mask="##:##" />
              <q-input class="col-6 col-sm-3" outlined v-model="end" label="終了" mask="##:##" />
            </div>
            <q-input outlined v-model="place" label="場所 / URL" placeholder="会議室A / https://...">
              <template v-slot:prepend><q-icon name="place" /></template>
            </q-input>
          </q-card-section>
        </q-card>

        <!-- アジェンダ -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="list_alt" class="q-mr-xs" />アジェンダ（Markdown可）
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <q-input outlined type="textarea" v-model="agenda" autogrow input-style="min-height:90px" />
          </q-card-section>
        </q-card>

        <!-- 参加者 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="group" class="q-mr-xs" />参加者リスト
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <q-banner v-if="participantsLocked" dense rounded class="bg-blue-1 text-blue-10 q-mb-sm">
              <template v-slot:avatar><q-icon name="lock" color="blue-8" /></template>
              完了した議事録では、文字起こしの話者ラベルを保つため参加者は変更できません。
            </q-banner>
            <q-list bordered separator class="rounded-borders q-mb-sm">
              <q-item v-for="(p, i) in participants" :key="i">
                <q-item-section avatar>
                  <q-avatar color="secondary" text-color="white">{{ p.name.charAt(0) }}</q-avatar>
                </q-item-section>
                <q-item-section>
                  <q-item-label>
                    {{ p.name }}
                    <q-badge v-if="p.role" outline color="grey-7" :label="p.role" class="q-ml-xs" />
                  </q-item-label>
                  <q-item-label caption>声の補足: {{ p.voice || "—" }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn
                    flat
                    round
                    dense
                    icon="close"
                    color="grey-6"
                    :disable="participantsLocked"
                    @click="removeParticipant(i)"
                  />
                </q-item-section>
              </q-item>
            </q-list>
            <div v-if="!participantsLocked" class="row q-col-gutter-sm items-center">
              <q-input class="col" dense outlined v-model="np.name" label="氏名 *" />
              <q-input class="col" dense outlined v-model="np.role" label="役職" />
              <q-input class="col" dense outlined v-model="np.voice" label="声の補足（例:男性/低音）" />
              <q-btn round color="primary" icon="add" @click="addParticipant" />
            </div>
          </q-card-section>
        </q-card>

        <!-- 専門用語 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="sell" class="q-mr-xs" />専門用語辞書
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <q-select
              outlined
              v-model="vocab"
              use-input
              use-chips
              multiple
              hide-dropdown-icon
              new-value-mode="add-unique"
              label="用語を入力してEnter（製品名・人名の特殊漢字など）"
            />
          </q-card-section>
        </q-card>

        <!-- 資料 -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="text-subtitle1 text-weight-medium">
              <q-icon name="attach_file" class="q-mr-xs" />参考資料（.xlsx / .pdf）
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section>
            <div class="dropzone q-pa-lg text-center text-grey-6 q-mb-sm">
              <q-icon name="cloud_upload" size="36px" />
              <div>ここにファイルをドラッグ＆ドロップ</div>
            </div>
            <q-list bordered separator class="rounded-borders">
              <q-item>
                <q-item-section avatar><q-icon name="grid_on" color="green-7" /></q-item-section>
                <q-item-section>
                  <q-item-label>FY26_予算案.xlsx</q-item-label>
                  <q-item-label caption>解析完了（extracted_text にキャッシュ）</q-item-label>
                </q-item-section>
                <q-item-section side><q-badge color="green-6" label="完了" /></q-item-section>
              </q-item>
              <q-item>
                <q-item-section avatar><q-icon name="picture_as_pdf" color="red-7" /></q-item-section>
                <q-item-section>
                  <q-item-label>製品仕様_v3.pdf</q-item-label>
                  <q-item-label caption>テキスト抽出中…</q-item-label>
                </q-item-section>
                <q-item-section side><q-spinner color="primary" size="18px" /></q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>

        <q-banner v-if="errorMsg" dense rounded class="bg-orange-2 q-mb-md text-orange-10">
          <template v-slot:avatar><q-icon name="warning" color="orange-9" /></template>
          保存に失敗しました（Tauri ランタイム上で実行していますか？）: {{ errorMsg }}
        </q-banner>

        <div class="row q-gutter-sm justify-end q-mb-xl">
          <q-btn flat no-caps label="キャンセル" @click="router.push('/s01')" />
          <q-btn
            outline
            no-caps
            color="primary"
            icon="save"
            :label="isEditing ? '変更を保存' : '保存して予約'"
            :loading="saving"
            @click="save"
          />
          <q-btn
            v-if="editingBase?.status !== 'completed'"
            unelevated
            no-caps
            color="primary"
            icon="play_arrow"
            label="この内容で会議を開始"
            @click="router.push('/s04')"
          />
        </div>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped>
.dropzone {
  border: 2px dashed #cbd5e1;
  border-radius: 8px;
}
</style>
