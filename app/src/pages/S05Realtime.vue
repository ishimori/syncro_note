<script setup lang="ts">
// S-05 リアルタイム議事録（会議中）— Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-05_realtime.html。
// 「確定テキストが主役（即時・不可変）／LLM整形は薄字の追い上げ」を反映。
// 中身（Python文字起こし）との接続は Phase 3 で行う。
import { ref, reactive } from "vue";
import AppNav from "../components/AppNav.vue";

interface AiSeg {
  type: "ai";
  speaker: string;
  t: string;
  text: string;
  refined: string | null;
  confirmed: boolean;
}
interface MemoSeg {
  type: "memo";
  t: string;
  text: string;
}
type TimelineItem = AiSeg | MemoSeg;

const leftDrawer = ref(true);

const drawer = ref(true);
const showRefined = ref(true);
const bypass = ref(false);
const elapsed = ref("00:12:34");
const latency = ref(2);
const drops = ref(0);

const participants = ["鈴木（PM）", "佐藤（エンジニア）", "田中（デザイナー）"];
const vocab = ["Qwen", "Tauri", "SQLite", "SynchroniNote", "diarization"];

// 確定話者マッピング（人間確定 > AI推測）
const mapping = reactive<Record<string, string>>({});

const timeline = reactive<TimelineItem[]>([
  {
    type: "ai",
    speaker: "Speaker_0",
    t: "00:01",
    text: "お疲れ様です。今日は基本設計のレビューから始めます。",
    refined: "お疲れ様です。本日は基本設計のレビューから始めます。",
    confirmed: false,
  },
  {
    type: "ai",
    speaker: "Speaker_1",
    t: "00:03",
    text: "えっと、確定テキストを主役にする方針で良いですよね。",
    refined: "確定テキストを主役にする方針で問題ありません。",
    confirmed: false,
  },
  {
    type: "memo",
    t: "00:04",
    text: "★ホワイトボード: 「LLM整形=追い上げレイヤ」の図を記載",
  },
  {
    type: "ai",
    speaker: "Speaker_0",
    t: "00:06",
    text: "はい。話者分離はwhisper非依存で、あー、PoCを別途やります。",
    refined: null,
    confirmed: false,
  },
]);

const displayName = (s: AiSeg): string => mapping[s.speaker] || s.speaker;

const assign = (sid: string, name: string): void => {
  mapping[sid] = name;
  timeline.forEach((x) => {
    if (x.type === "ai" && x.speaker === sid) x.confirmed = true;
  });
};

const memo = ref("");
const sendMemo = (): void => {
  if (memo.value.trim()) {
    timeline.push({ type: "memo", t: elapsed.value.slice(3), text: memo.value });
    memo.value = "";
  }
};
</script>

<template>
  <q-layout view="hHh LpR fFf">
    <!-- 左ドロワー: 画面ナビ（全画面共有。クリックでルーター遷移） -->
    <AppNav v-model="leftDrawer" />

    <!-- ヘッダ: 録音状態・経過・遅延ゲージ・drop・終了 -->
    <q-header elevated class="bg-primary text-white">
      <q-toolbar>
        <q-btn flat round dense icon="menu" @click="leftDrawer = !leftDrawer" class="q-mr-xs">
          <q-tooltip>画面メニュー</q-tooltip>
        </q-btn>
        <span class="rec-dot q-mr-sm" />
        <q-toolbar-title>設計レビュー — 録音中</q-toolbar-title>
        <q-chip dense color="white" text-color="primary" icon="schedule" :label="elapsed" class="q-mr-sm" />
        <q-chip
          dense
          :color="latency > 3 ? 'red-4' : 'green-4'"
          text-color="white"
          icon="speed"
          :label="'遅延 ' + latency + 's'"
          class="q-mr-sm"
        >
          <q-tooltip>整形バックログ（主役の確定表示は0遅延）</q-tooltip>
        </q-chip>
        <q-chip dense color="grey-4" text-color="dark" icon="warning" :label="'drop ' + drops" />
        <q-btn unelevated no-caps color="red-6" icon="stop" label="会議を終了" class="q-ml-md" />
      </q-toolbar>
      <q-bar class="bg-indigo-2 text-indigo-10" v-if="bypass">
        <q-icon name="bolt" /> 処理が詰まったため LLM整形をバイパス中（生テキストを優先表示）
      </q-bar>
    </q-header>

    <!-- 右ドロワー: コンテキスト参照（デスクトップでは常時ドッキング＝背景を暗くしない） -->
    <q-drawer side="right" v-model="drawer" show-if-above bordered :width="280">
      <q-scroll-area class="fit">
        <q-list padding>
          <q-item-label header>アジェンダ</q-item-label>
          <q-item>
            <q-item-section>1. 基本設計のレビュー<br />2. 話者分離方式の確定<br />3. DD候補</q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item-label header>参加者</q-item-label>
          <q-item v-for="p in participants" :key="p">
            <q-item-section avatar>
              <q-avatar size="28px" color="secondary" text-color="white">{{ p.charAt(0) }}</q-avatar>
            </q-item-section>
            <q-item-section>{{ p }}</q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item-label header>専門用語</q-item-label>
          <q-item>
            <q-item-section>
              <div class="q-gutter-xs">
                <q-badge v-for="w in vocab" :key="w" outline color="primary" :label="w" />
              </div>
            </q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item>
            <q-item-section>
              <q-toggle v-model="showRefined" label="LLM整形を表示" color="primary" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>
    </q-drawer>

    <!-- メイン: 確定タイムライン（主役）＋人間メモ -->
    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 900px; margin: 0 auto">
        <q-banner dense rounded class="bg-amber-1 q-mb-sm text-grey-9">
          <template v-slot:avatar><q-icon name="info" color="amber-8" /></template>
          <b>確定文字起こしが主役</b>（即時・不可変）。LLM整形は薄い字の<b>追い上げ表示</b>。話者名をクリックすると参加者から選んで一括置換できます。
          <q-btn flat dense round icon="menu_open" @click="drawer = !drawer" class="float-right">
            <q-tooltip>コンテキスト</q-tooltip>
          </q-btn>
        </q-banner>

        <q-card flat bordered>
          <q-card-section>
            <div v-for="(s, i) in timeline" :key="i">
              <!-- 人間メモ -->
              <template v-if="s.type === 'memo'">
                <q-chat-message :name="'📝人間メモ'" :text="[s.text]" :stamp="s.t" sent bg-color="orange-2" />
              </template>
              <!-- AI確定セグメント -->
              <template v-else>
                <div class="seg">
                  <div class="row items-center">
                    <q-badge :color="s.confirmed ? 'secondary' : 'grey-5'" class="q-mr-sm">
                      <span class="spk">{{ displayName(s) }}</span>
                      <q-icon name="arrow_drop_down" />
                      <q-menu>
                        <q-list style="min-width: 180px">
                          <q-item-label header>話者を確定</q-item-label>
                          <q-item
                            v-for="p in participants"
                            :key="p"
                            clickable
                            v-close-popup
                            @click="assign(s.speaker, p)"
                          >
                            <q-item-section>{{ p }}</q-item-section>
                          </q-item>
                        </q-list>
                      </q-menu>
                    </q-badge>
                    <span class="text-caption text-grey-6">{{ s.t }}</span>
                    <q-badge v-if="!s.refined" outline color="grey-6" label="unrefined" class="q-ml-sm">
                      <q-tooltip>整形待ち（生テキスト表示中）</q-tooltip>
                    </q-badge>
                  </div>
                  <div class="q-mt-xs">{{ s.text }}</div>
                  <div v-if="showRefined && s.refined" class="refined">
                    <q-icon name="auto_fix_high" size="14px" /> {{ s.refined }}
                  </div>
                </div>
              </template>
            </div>
            <!-- 生成中（タイピング中）チャンク -->
            <div class="seg">
              <div class="row items-center">
                <q-badge color="grey-5" class="q-mr-sm">Speaker_0 <q-icon name="arrow_drop_down" /></q-badge>
                <span class="text-caption text-grey-6">{{ elapsed }}</span>
              </div>
              <div class="q-mt-xs">
                それでは次のアジェンダ、話者分離の方式について<q-spinner-dots color="primary" size="1.4em" />
              </div>
            </div>
          </q-card-section>
        </q-card>
        <div style="height: 80px" />
      </q-page>
    </q-page-container>

    <!-- フッタ: 人間メモ入力 -->
    <q-footer class="bg-white text-dark" bordered>
      <q-toolbar class="q-py-sm" style="max-width: 900px; margin: 0 auto; width: 100%">
        <q-btn flat round dense icon="pause" color="grey-7"><q-tooltip>一時停止</q-tooltip></q-btn>
        <q-input
          class="col q-mx-sm"
          outlined
          dense
          v-model="memo"
          placeholder="📝 人間メモを入力（ホワイトボードの内容・口頭指示など）… Enterで挿入"
          @keyup.enter="sendMemo"
        >
          <template v-slot:prepend><q-icon name="edit_note" /></template>
        </q-input>
        <q-btn round color="primary" icon="send" @click="sendMemo" />
      </q-toolbar>
    </q-footer>
  </q-layout>
</template>

<style scoped>
.rec-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  display: inline-block;
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0.3;
  }
}
.refined {
  color: #64748b;
  font-size: 0.85em;
  border-left: 2px solid #cbd5e1;
  padding-left: 8px;
  margin-top: 2px;
}
.spk {
  cursor: pointer;
  border-bottom: 1px dashed #94a3b8;
}
.seg {
  border-bottom: 1px solid #f1f5f9;
  padding: 8px 0;
}
</style>
