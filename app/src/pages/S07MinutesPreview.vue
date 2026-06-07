<script setup lang="ts">
// S-07 議事録プレビュー（生成直後）— Phase 2: 静的骨格（見た目＋ローカル操作のみ）。
// 正＝設計SSOT doc/spec/画面設計書.md ＋ doc/mock/html/S-07_minutes-preview.html。
// 清書完了の最終議事録（Markdown）を表示し、編集トグルでソース編集に切替える。
// 保存/コピー/エクスポートは見た目のみ（実I/O・Tauri連携は Phase 3 以降）。
import { ref } from "vue";
import { useRouter } from "vue-router";
import AppNav from "../components/AppNav.vue";

const router = useRouter();

const leftDrawer = ref(true);
const editMode = ref(false);
const src = ref(
  "## ■ 会議概要\n基本設計レビューを実施。確定テキスト即表示を主役とする方針を確認。\n\n## ■ 決定事項\n- 佐藤：話者分離PoCを6/20までに\n- 鈴木：清書モデルを gemma4:26b に確定\n\n## ■ アクションアイテム\n- [ ] DD-004 起票（佐藤）"
);
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
        <q-toolbar-title>議事録プレビュー（生成完了）</q-toolbar-title>
        <q-toggle v-model="editMode" color="white" keep-color label="編集" left-label class="q-mr-md" />
        <q-btn flat dense no-caps icon="content_copy" label="コピー" />
        <q-btn
          unelevated
          no-caps
          color="green-6"
          icon="save"
          label="保存（completed）"
          class="q-ml-sm"
          @click="router.push('/s01')"
        />
      </q-toolbar>
    </q-header>

    <q-page-container>
      <q-page class="q-pa-md" style="max-width: 960px; margin: 0 auto">
        <q-banner dense rounded class="bg-green-1 q-mb-md text-grey-9">
          <template v-slot:avatar><q-icon name="check_circle" color="green-6" /></template>
          清書が完了しました（gemma4:26b・所要 4分12秒）。内容を確認し、必要なら微修正して保存してください。保存で
          <code>final_minutes</code> 更新・<code>status='completed'</code>。
        </q-banner>

        <q-card flat bordered>
          <q-card-section class="row items-center">
            <div class="text-h6">設計レビュー</div>
            <q-space />
            <q-badge outline color="grey-7" label="2026/06/18 13:00–14:05" />
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
            <h2>■ 会議概要</h2>
            <ul>
              <li>
                基本設計レビューを実施。確定テキスト即表示を主役とする方針を確認。リアルタイム整形は追い上げレイヤに格下げ。
              </li>
            </ul>
            <h2>■ 決定事項（誰が・何を・いつまでに）</h2>
            <ul>
              <li>佐藤：話者分離PoC（pyannote / sherpa-onnx, CPU）を 6/20 までに実施。</li>
              <li>鈴木：清書モデルを gemma4:26b に確定。UIの所要時間表示を実測 3〜6分へ修正。</li>
            </ul>
            <h2>■ 保留事項・次回の課題</h2>
            <ul>
              <li>32B密モデルの要否、iGPU(780M)部分オフロードは余力で検証。</li>
            </ul>
            <h2>■ アクションアイテム（担当付き）</h2>
            <ul>
              <li>[ ] DD-004 起票（佐藤・6/9）</li>
              <li>[ ] 要件File 5 の文言修正（鈴木・6/9）</li>
            </ul>
            <h2>■ 各アジェンダの議論詳細</h2>
            <ul>
              <li>
                <b>基本設計</b>：CPUのtok/s実測から、会議中にLLMで全文整形すると破綻。確定テキストを主役に。
              </li>
              <li><b>話者分離</b>：whisper非依存スタックで終了後一括ラベリング＋人間名寄せ。</li>
              <li><b>人間メモ</b>：★社長指示「予算上限150万」は清書でも最優先・全文保持。</li>
            </ul>
          </q-card-section>
        </q-card>

        <div class="row q-gutter-sm justify-end q-mt-md q-mb-xl">
          <q-btn flat no-caps label="カレンダーへ戻る" icon="arrow_back" @click="router.push('/s01')" />
          <q-btn outline no-caps color="primary" icon="download" label="エクスポート" />
          <q-btn
            unelevated
            no-caps
            color="green-6"
            icon="save"
            label="保存して完了"
            @click="router.push('/s01')"
          />
        </div>
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
  margin: 0.25em 0;
}
</style>
