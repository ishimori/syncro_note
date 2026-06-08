// DD-013-2: 人間メモCRDT層のマージ正当性を機械検証する。
//   - 最小差分は中央だけを書き換え、別位置の並行挿入を壊さない
//   - AI自動追記 vs 人間入力を交互にマージ→収束（両レプリカ一致）・CRC一致・文字喪失0（=衝突0）
//   - 500字以上の連続編集でも上記を満たし、マージ計算は 200ms 以内（再描画は別途）
import { describe, it, expect } from "vitest";
import * as Y from "yjs";
import { useMemoDoc, applyMinimalEdit, checksum, syncDocs, LocalProvider } from "./memoDoc";

describe("applyMinimalEdit（最小差分・broadcast全置換をしない）", () => {
  it("中央の変更だけを書き換える", () => {
    const doc = new Y.Doc();
    const t = doc.getText("memo");
    t.insert(0, "ABCDEFG");
    applyMinimalEdit(doc, t, "ABCXEFG", null); // D→X だけ
    expect(t.toString()).toBe("ABCXEFG");
  });

  it("別位置への並行編集を壊さない（前方=B挿入 / 後方=A編集 がどちらも残る）", () => {
    const a = new Y.Doc();
    const b = new Y.Doc();
    a.getText("memo").insert(0, "hello");
    syncDocs(a, b); // 共通基底 "hello"
    applyMinimalEdit(a, a.getText("memo"), "hello world", null); // 末尾追記
    applyMinimalEdit(b, b.getText("memo"), ">> hello", null); // 先頭挿入
    syncDocs(a, b);
    const ma = a.getText("memo").toString();
    const mb = b.getText("memo").toString();
    expect(ma).toBe(mb); // 収束
    expect(ma.includes("world")).toBe(true);
    expect(ma.includes(">>")).toBe(true);
  });
});

describe("CRDTマージ: 500字連続編集で衝突0・CRC一致（DD-013-2 DoD）", () => {
  it("AI末尾追記 vs 人間先頭入力を交互同期→収束・CRC一致・文字喪失0・計算<200ms", () => {
    const human = useMemoDoc(new LocalProvider()); // 人間側レプリカ
    const ai = useMemoDoc(new LocalProvider()); // AI側レプリカ（別クライアント相当）
    syncDocs(human.doc, ai.doc); // 空の共通基底

    const aiChunk = "AI確定セグメントの追記。"; // 12文字（削除を伴わない純追記）
    let expectedLen = 0;
    const rounds = 40; // 13字/round × 40 = 520字（>500）

    const t0 = performance.now();
    for (let r = 0; r < rounds; r++) {
      // AI: 末尾へ追記
      ai.append(aiChunk);
      expectedLen += aiChunk.length;
      // 人間: 現在の表示(マージ済み)の先頭に1文字を足してフル文字列で setText（textarea と同じ流儀）
      const typed = String(r % 10) + human.text.value;
      human.setText(typed);
      expectedLen += 1;
      // 双方向同期（差分のみ交換）
      syncDocs(human.doc, ai.doc);
    }
    const elapsedMs = performance.now() - t0;

    const mh = human.text.value;
    const ma = ai.text.value;
    expect(mh).toBe(ma); // 収束（両レプリカ一致）
    expect(checksum(mh)).toBe(checksum(ma)); // CRC一致
    expect(mh.length).toBe(expectedLen); // 文字喪失0（=衝突で消えた文字がない）
    expect(mh.length).toBeGreaterThanOrEqual(500); // 500字以上
    expect(elapsedMs).toBeLessThan(200); // マージ計算は 200ms 以内（再描画は別途・基本設計書SLA）
  });
});

describe("競合ロギング（並行編集が重なった回数）", () => {
  it("同一位置近傍への並行挿入を検出してカウントし、なお収束する", () => {
    const a = useMemoDoc(new LocalProvider());
    const b = useMemoDoc(new LocalProvider());
    a.setText("hello");
    syncDocs(a.doc, b.doc);
    a.setText("Xhello"); // a: 先頭(index0)を編集 → lastLocalEditAt=0
    b.insertAt(0, "Y"); // b: 先頭へ並行挿入
    syncDocs(a.doc, b.doc); // a から見て index0 近傍に他者挿入 → 競合として計上
    expect(a.text.value).toBe(b.text.value); // 収束（破壊なし）
    expect(a.conflictCount.value).toBeGreaterThanOrEqual(1); // 競合検出
    expect(a.text.value.length).toBe(7); // "hello"(5)+X+Y、喪失なし
  });
});
