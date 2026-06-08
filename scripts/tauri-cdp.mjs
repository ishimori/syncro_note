#!/usr/bin/env node
// =============================================================================
// tauri-cdp.mjs — 実Tauriウィンドウ(WebView2)を Claude から操作するドライバ
//
// なぜ必要か:
//   素のブラウザ(Playwright)で localhost:1420 を開くと Tauri ランタイム
//   (invoke/イベント/Rust側) が無く「見た目だけ」しか確認できない。
//   一方、開発起動した *実ウィンドウ* には WebView2 のデバッグ窓口(CDP)が開いて
//   いるので、そこへ直結すれば invoke/Rust/実DB 込みで本物を操作できる。
//
// 前提:
//   `bash scripts/start-app.sh` で起動していること（同スクリプトが
//   WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 を付与）。
//   Node v18+（global fetch / WebSocket を使用。動作確認は v22）。
//
// 使い方（リポジトリルートから）:
//   node scripts/tauri-cdp.mjs snapshot                 # 操作可能な要素を一覧（画面を“読む”）
//   node scripts/tauri-cdp.mjs text  "<cssSelector>"    # 要素のテキストを取得
//   node scripts/tauri-cdp.mjs click "<cssSelector>"    # 要素をクリック
//   node scripts/tauri-cdp.mjs eval  "<js式>"           # 任意JSを評価(Promiseは解決して返す)
//   node scripts/tauri-cdp.mjs invoke <cmd> '<jsonArgs>'# Rustコマンドを直接呼ぶ 例: invoke list_meetings '{"year":2026,"month":6}'
//   node scripts/tauri-cdp.mjs shot  <out.png>          # 実ウィンドウのスクショ(PNG)
//
// 注意:
//   - クリックは要素の synthetic click（Vue/Quasarのハンドラはこれで発火する）。
//     ピクセル精度のドラッグ等が要るときは shot-window.ps1 + 座標系の手段を使う。
//   - 破壊的操作(削除/保存)も実DBに効く。確認系は list_*/get_* を使うこと。
// =============================================================================
const BASE = "http://localhost:9222";

async function connect() {
  let pages;
  try {
    pages = await (await fetch(`${BASE}/json`)).json();
  } catch {
    fail(`CDPに接続できません(${BASE})。先に bash scripts/start-app.sh で起動してください。`);
  }
  const page = pages.find((p) => p.type === "page" && p.url.includes("localhost:1420"));
  if (!page) fail("Tauriのページ(localhost:1420)が見つかりません。ウィンドウが開いているか確認してください。");

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  await new Promise((r) => ws.addEventListener("open", r));
  const send = (method, params = {}) =>
    new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Runtime.enable");
  return { send, close: () => ws.close(), page };
}

async function evalJs(send, expression, awaitPromise = false) {
  const m = await send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
  if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description || m.result.exceptionDetails.text);
  return m.result?.result?.value;
}

function fail(msg) { console.error("[tauri-cdp] " + msg); process.exit(1); }
function out(v) { console.log(typeof v === "string" ? v : JSON.stringify(v, null, 2)); }

const [cmd, a1, a2] = process.argv.slice(2);
const { send, close, page } = await connect();
try {
  switch (cmd) {
    case "snapshot": {
      const v = await evalJs(send, `
        Array.from(document.querySelectorAll('button,a,input,[role="button"],[role="tab"],.q-item'))
          .map((el,i) => ({
            i, tag: el.tagName.toLowerCase(),
            text: (el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,40),
            id: el.id||undefined,
            cls: (el.className&&typeof el.className==='string')? el.className.split(/\\s+/).slice(0,2).join('.') : undefined
          }))
          .filter(o => o.text || o.id)
      `);
      out({ url: page.url, title: page.title, elements: v });
      break;
    }
    case "text": {
      if (!a1) fail("使い方: text \"<cssSelector>\"");
      out(await evalJs(send, `document.querySelector(${JSON.stringify(a1)})?.innerText ?? null`));
      break;
    }
    case "click": {
      if (!a1) fail("使い方: click \"<cssSelector>\"");
      const r = await evalJs(send, `(()=>{const el=document.querySelector(${JSON.stringify(a1)}); if(!el) return 'NOT_FOUND'; el.click(); return 'CLICKED:'+(el.innerText||el.id||el.tagName);})()`);
      if (r === "NOT_FOUND") fail(`要素が見つかりません: ${a1}`);
      out(r);
      break;
    }
    case "eval": {
      if (!a1) fail("使い方: eval \"<js式>\"");
      out(await evalJs(send, a1, true));
      break;
    }
    case "invoke": {
      if (!a1) fail("使い方: invoke <cmd> '<jsonArgs>'");
      const args = a2 ? a2 : "{}";
      const r = await evalJs(send,
        `window.__TAURI_INTERNALS__.invoke(${JSON.stringify(a1)}, ${args})`, true);
      out(r);
      break;
    }
    case "shot": {
      if (!a1) fail("使い方: shot <out.png>");
      const m = await send("Page.captureScreenshot", { format: "png" });
      const b64 = m.result?.data;
      if (!b64) fail("スクショ取得に失敗しました。");
      const { writeFileSync } = await import("node:fs");
      writeFileSync(a1, Buffer.from(b64, "base64"));
      out("SAVED: " + a1);
      break;
    }
    default:
      fail("コマンド: snapshot | text | click | eval | invoke | shot （詳細はファイル先頭コメント）");
  }
} catch (e) {
  fail("実行エラー: " + e.message);
} finally {
  close();
}
