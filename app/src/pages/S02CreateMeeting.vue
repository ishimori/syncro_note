<script setup lang="ts">
// S-02 会議作成・事前登録 — DD-012-3 で作成→保存、DD-012-9 Phase 4 で編集モードを追加。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-02_create-meeting.html。
// ここで入力した前提（参加者・アジェンダ・用語・資料）が、リアルタイム補正と
// 終了後の清書プロンプトに渡る。本フェーズでは基本情報＋参加者を `meetings`/`participants` に保存する。
//   id・各時刻は frontend で確定して渡す（Rust DB層の純関数設計に合わせる）。
// 編集モード（?id=）: 既存会議を読み込み、`update_meeting` で更新。完了会議は参加者を保護（話者リンク保全）。
// 新規（?date=YYYY-MM-DD）: 空きセルからの遷移で日付を初期化する。
import { ref, reactive, computed, onMounted, watch } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useQuasar } from "quasar";
import { open } from "@tauri-apps/plugin-dialog";
import AppNav from "../components/AppNav.vue";
import { setAppTitle } from "../title";
import {
  createMeeting,
  updateMeeting,
  getMeetingDetail,
  addAttachment,
  listAttachments,
  removeAttachment,
  localIso,
  type Meeting,
  type Participant as DbParticipant,
  type Attachment,
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

// 参考資料（DD-012-10）
// 添付は meeting_id 必須（FK）。新規作成時はまだ会議が無いので「保存待ち列」に貯め、保存時に取り込む。
// 編集モードは会議が存在するので即時に取り込む（コピー＋オフライン抽出）。
const newMeetingId = crypto.randomUUID(); // 新規用に1度だけ採番（保存時もこのidで作る）
const meetingId = computed<string>(() => editingBase.value?.id ?? newMeetingId);
const savedAttachments = ref<Attachment[]>([]); // 取り込み済み（編集ロード or 即時追加の結果）
interface PendingFile {
  localId: string;
  path: string;
  name: string;
  type: "xlsx" | "pdf";
}
const pendingFiles = ref<PendingFile[]>([]); // 新規作成での保存待ち
const attaching = ref(false); // ダイアログ選択〜抽出中

const fileTypeOf = (name: string): "xlsx" | "pdf" | null => {
  const l = name.toLowerCase();
  if (l.endsWith(".xlsx")) return "xlsx";
  if (l.endsWith(".pdf")) return "pdf";
  return null;
};

// 「資料を追加」: OSのファイル選択（実パスを得るため。webViewの input[type=file] は実パスを返さない）。
const pickFiles = async (): Promise<void> => {
  const selected = await open({
    multiple: true,
    filters: [{ name: "資料 (Excel / PDF)", extensions: ["xlsx", "pdf"] }],
  });
  if (selected === null) return;
  const paths = Array.isArray(selected) ? selected : [selected];
  for (const path of paths) {
    const name = path.split(/[\\/]/).pop() ?? path;
    const type = fileTypeOf(name);
    if (!type) {
      $q.notify({ message: `未対応のファイルです: ${name}`, color: "warning", icon: "block" });
      continue;
    }
    if (isEditing.value) {
      // 既存会議 → 即時にコピー＋抽出（数秒）。結果（done/error）を一覧へ。
      attaching.value = true;
      try {
        const a = await addAttachment(crypto.randomUUID(), meetingId.value, path, name, type, localIso());
        savedAttachments.value.push(a);
      } catch (e) {
        errorMsg.value = String(e);
      } finally {
        attaching.value = false;
      }
    } else {
      // 新規 → 保存待ち列へ（保存時にまとめて取り込む）。
      pendingFiles.value.push({ localId: crypto.randomUUID(), path, name, type });
    }
  }
};

const removeSaved = async (id: string): Promise<void> => {
  try {
    await removeAttachment(id);
    savedAttachments.value = savedAttachments.value.filter((a) => a.id !== id);
  } catch (e) {
    errorMsg.value = String(e);
  }
};
const removePending = (localId: string): void => {
  pendingFiles.value = pendingFiles.value.filter((f) => f.localId !== localId);
};

// 添付の表示用ヘルパ（種別アイコン・状態ラベル）。
const attachIcon = (type: string): string => (type === "xlsx" ? "grid_on" : "picture_as_pdf");
const attachIconColor = (type: string): string => (type === "xlsx" ? "green-7" : "red-7");
const isEmptyExtract = (a: Attachment): boolean =>
  a.parse_status === "done" && !(a.extracted_text && a.extracted_text.trim());
// 抽出済み（done かつ本文あり）＝プレビュー可能。
const canPreview = (a: Attachment): boolean =>
  a.parse_status === "done" && !!(a.extracted_text && a.extracted_text.trim());

// 抽出テキストのプレビュー（清書まで進めず、いつでも中身を確認する・DD-012-10）。
const previewOpen = ref(false);
const previewName = ref("");
const previewText = ref("");
const openPreview = (a: Attachment): void => {
  previewName.value = a.file_name;
  previewText.value = a.extracted_text ?? "";
  previewOpen.value = true;
};
const copyPreview = async (): Promise<void> => {
  try {
    await navigator.clipboard.writeText(previewText.value);
    $q.notify({ message: "抽出テキストをコピーしました", color: "indigo", icon: "content_copy", timeout: 1500 });
  } catch {
    $q.notify({ message: "コピーに失敗しました", color: "negative", icon: "error" });
  }
};

// 保存処理
const saving = ref(false);
const errorMsg = ref("");

// 編集モード状態
const editingBase = ref<Meeting | null>(null); // 読み込んだ会議（id/status/created_at/清書 等を温存）
const isEditing = computed<boolean>(() => editingBase.value !== null);
// 完了会議は参加者をロック（変更すると timeline_elements.confirmed_participant_id の話者リンクが切れるため）。
const participantsLocked = computed<boolean>(() => editingBase.value?.status === "completed");

// OSウィンドウのタイトルに「会議名＋日付」を出す（今どの予定を編集/作成中かを一目で）。入力にも追従させる。
watch(
  [title, date, isEditing],
  () => {
    const name = title.value.trim() || (isEditing.value ? "（無題）" : "新規会議");
    setAppTitle(`${name} ${date.value}・${isEditing.value ? "会議の編集" : "会議の作成"}`);
  },
  { immediate: true },
);

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
      savedAttachments.value = await listAttachments(id); // 既存の添付を表示（DD-012-10）
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
      const id = meetingId.value; // 新規用に採番済みのid（添付の保存待ち列と一致させる）
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
      // 会議が出来てから保存待ちの資料を取り込む（コピー＋オフライン抽出）。失敗は通知のみで保存は妨げない。
      for (const f of pendingFiles.value) {
        try {
          await addAttachment(crypto.randomUUID(), id, f.path, f.name, f.type, localIso());
        } catch (e) {
          $q.notify({ message: `資料「${f.name}」の取り込みに失敗`, caption: String(e), color: "warning" });
        }
      }
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

        <!-- 資料（DD-012-10: Excel/PDF をオフライン抽出して清書の前提資料にする） -->
        <q-card flat bordered class="q-mb-md">
          <q-card-section class="row items-center">
            <div class="text-subtitle1 text-weight-medium col">
              <q-icon name="attach_file" class="q-mr-xs" />参考資料（.xlsx / .pdf）
            </div>
            <q-btn
              outline
              no-caps
              dense
              color="primary"
              icon="add"
              label="資料を追加"
              :loading="attaching"
              @click="pickFiles"
            />
          </q-card-section>
          <q-separator />
          <q-card-section>
            <div
              v-if="savedAttachments.length === 0 && pendingFiles.length === 0"
              class="text-grey-6 text-center q-py-md"
            >
              <q-icon name="upload_file" size="28px" class="q-mb-xs" />
              <div>「資料を追加」で Excel/PDF を選ぶと、本文を取り出して清書に活かします（完全オフライン）。</div>
            </div>
            <q-list v-else bordered separator class="rounded-borders">
              <!-- 取り込み済み（保存済み・編集ロード分） -->
              <q-item v-for="a in savedAttachments" :key="a.id">
                <q-item-section avatar>
                  <q-icon :name="attachIcon(a.file_type)" :color="attachIconColor(a.file_type)" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ a.file_name }}</q-item-label>
                  <q-item-label caption>
                    <span v-if="a.parse_status === 'pending'">解析中…</span>
                    <span v-else-if="a.parse_status === 'error'" class="text-negative">抽出に失敗しました</span>
                    <span v-else-if="isEmptyExtract(a)" class="text-orange-9">
                      テキストを取得できません（画像PDFの可能性）
                    </span>
                    <span v-else>解析完了（清書に反映されます）</span>
                  </q-item-label>
                </q-item-section>
                <q-item-section side class="row items-center no-wrap">
                  <q-spinner v-if="a.parse_status === 'pending'" color="primary" size="18px" class="q-mr-sm" />
                  <q-badge v-else-if="a.parse_status === 'error'" color="red-6" label="失敗" class="q-mr-sm" />
                  <q-badge v-else-if="isEmptyExtract(a)" color="orange-7" label="本文なし" class="q-mr-sm" />
                  <q-badge v-else color="green-6" label="完了" class="q-mr-sm" />
                  <q-btn
                    v-if="canPreview(a)"
                    flat
                    round
                    dense
                    icon="visibility"
                    color="primary"
                    @click="openPreview(a)"
                  >
                    <q-tooltip>抽出テキストを確認</q-tooltip>
                  </q-btn>
                  <q-btn flat round dense icon="close" color="grey-6" @click="removeSaved(a.id)" />
                </q-item-section>
              </q-item>
              <!-- 保存待ち（新規作成。保存時に取り込む） -->
              <q-item v-for="f in pendingFiles" :key="f.localId">
                <q-item-section avatar>
                  <q-icon :name="attachIcon(f.type)" :color="attachIconColor(f.type)" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ f.name }}</q-item-label>
                  <q-item-label caption>保存時に取り込みます</q-item-label>
                </q-item-section>
                <q-item-section side class="row items-center no-wrap">
                  <q-badge color="grey-5" label="保存待ち" class="q-mr-sm" />
                  <q-btn flat round dense icon="close" color="grey-6" @click="removePending(f.localId)" />
                </q-item-section>
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

    <!-- 抽出テキストのプレビュー（清書まで進めず中身を確認・DD-012-10） -->
    <q-dialog v-model="previewOpen">
      <q-card style="width: 720px; max-width: 92vw">
        <q-card-section class="row items-center q-pb-none">
          <q-icon name="description" color="primary" class="q-mr-sm" />
          <div class="text-subtitle1 ellipsis">{{ previewName }}</div>
          <q-space />
          <q-btn flat dense no-caps size="sm" icon="content_copy" label="コピー" color="primary" @click="copyPreview" />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="text-caption text-grey-7 q-pt-xs">
          AIの清書に渡るのと同じ内容です。シート/ページごとに見出し・寸法・表へ構造化しています。
        </q-card-section>
        <q-separator />
        <q-card-section>
          <pre class="extract-preview">{{ previewText }}</pre>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-layout>
</template>

<style scoped>
.extract-preview {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 55vh;
  overflow: auto;
  margin: 0;
  font-size: 0.85rem;
  color: #334155;
}
</style>

