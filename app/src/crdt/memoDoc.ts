// DD-013-1/-2/-3: 人間メモを Yjs(CRDT) で「同時に編集しても壊れない」共有テキストにする基盤。
// 設計原則(基本設計書 §3.2): 確定文字起こしは immutable・CRDT 対象外。CRDT は人間メモ／整形レイヤに限定。
//   状態更新は single-flight（doc.transact で直列化）。broadcast channel は使わない。
// Rust/Python 非依存（フロントのみ）。Yjs は軽量 Rust ラッパーが無いため Rust の SessionState と二重管理しない。
import * as Y from "yjs";
import { ref, onUnmounted, getCurrentInstance, type Ref } from "vue";

// ローカル発の変更を識別する origin（observe のフィードバック判定＋競合ロギングに使う）。
export const LOCAL_ORIGIN = Symbol("memo-local");

/**
 * Yjs provider 抽象（DD-013-3）。
 * 将来の複数クライアント同期（y-websocket 等）を差し込むための口。
 * 既定はローカル単独（ネットワークなし）で、単独UIでも必ず動く。
 */
export interface MemoProvider {
  readonly name: string;
  connect(doc: Y.Doc): void;
  disconnect(): void;
}

/** ローカル単独 provider（ネットワークなし・no-op）。既定値。 */
export class LocalProvider implements MemoProvider {
  readonly name = "local";
  connect(_doc: Y.Doc): void {
    /* 単独動作なので接続先はない */
  }
  disconnect(): void {
    /* no-op */
  }
}

/**
 * old → next の最小編集を Y.Text へ適用する（前方一致・後方一致を保ち、中央の差分だけ delete+insert）。
 * テキスト全置換（全 delete → 全 insert）は並行編集を壊す（基本設計書が禁じる broadcast 相当）ため不可。
 * 中央差分のみ触ることで、別クライアント／AIが別位置に入れた挿入とマージしても衝突しない。
 */
export function applyMinimalEdit(doc: Y.Doc, ytext: Y.Text, next: string, origin: unknown): void {
  const cur = ytext.toString();
  if (cur === next) return;
  const minLen = Math.min(cur.length, next.length);
  let p = 0;
  while (p < minLen && cur[p] === next[p]) p++;
  let s = 0;
  while (s < minLen - p && cur[cur.length - 1 - s] === next[next.length - 1 - s]) s++;
  const delLen = cur.length - p - s;
  const insStr = next.slice(p, next.length - s);
  doc.transact(() => {
    if (delLen > 0) ytext.delete(p, delLen);
    if (insStr.length > 0) ytext.insert(p, insStr);
  }, origin);
}

/** 文字列のチェックサム（FNV-1a 32bit）。マージ結果の一致検証(DD-013-2 の「CRC一致」)に使う。 */
export function checksum(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * 2つの Y.Doc を相互同期（互いに欠けている差分だけ交換）。
 * テストの「並行編集→マージ」検証に使い、将来のネットワーク provider 実装の参照にもなる。
 */
export function syncDocs(a: Y.Doc, b: Y.Doc): void {
  const ua = Y.encodeStateAsUpdate(a, Y.encodeStateVector(b));
  const ub = Y.encodeStateAsUpdate(b, Y.encodeStateVector(a));
  Y.applyUpdate(b, ua);
  Y.applyUpdate(a, ub);
}

export interface MemoDoc {
  doc: Y.Doc;
  ytext: Y.Text;
  /** 表示用の reactive な現在値（Y.Text の変化で自動更新）。 */
  text: Ref<string>;
  /** 競合（並行編集が重なった）検出回数。破壊ではなくCRDTが解決した回数の診断ログ（DD-013-2）。 */
  conflictCount: Ref<number>;
  /** 人間入力を最小差分で反映（textarea の @update:model-value から呼ぶ）。 */
  setText: (next: string) => void;
  /** 末尾へ追記（左→右コピー / AI追記）。改行や区切りは呼び出し側で付与。DD-013-3。 */
  append: (chunk: string) => void;
  /** 任意位置へ挿入（将来用）。 */
  insertAt: (index: number, chunk: string) => void;
  destroy: () => void;
}

/**
 * 人間メモ用の CRDT ドキュメントを生成して Vue に結線する。
 * - text(Ref) は Y.Text の変化で自動更新（リモート/AI 追記も反映）。
 * - setText は最小差分のみ適用し、並行編集を壊さない（single-flight = doc.transact）。
 * - provider を差し替えれば将来ネットワーク同期に拡張できる（既定はローカル単独）。
 */
export function useMemoDoc(provider: MemoProvider = new LocalProvider()): MemoDoc {
  const doc = new Y.Doc();
  const ytext = doc.getText("memo");
  const text = ref<string>(ytext.toString());
  const conflictCount = ref(0);

  let lastLocalEditAt = -1; // 直近にローカルが触れた index（競合判定の窓の基準）

  const observer = (event: Y.YTextEvent, tr: Y.Transaction): void => {
    text.value = ytext.toString();
    // 競合ロギング: 別 origin（リモート/AI）由来の変更が、直近のローカル編集位置の近傍に入ったら
    // 「並行編集が重なった（CRDTがマージした）」とみなして数える。破壊的衝突ではない（Yjsが解決）。
    if (tr.origin !== LOCAL_ORIGIN && lastLocalEditAt >= 0) {
      let idx = 0;
      let near = false;
      for (const d of event.delta) {
        if (d.retain != null) {
          idx += d.retain;
        } else if (typeof d.insert === "string") {
          if (Math.abs(idx - lastLocalEditAt) <= Math.max(8, d.insert.length)) near = true;
          idx += d.insert.length;
        } else if (d.delete != null) {
          if (Math.abs(idx - lastLocalEditAt) <= Math.max(8, d.delete)) near = true;
        }
      }
      if (near) conflictCount.value++;
    }
  };
  ytext.observe(observer);
  provider.connect(doc);

  const setText = (next: string): void => {
    // 変更開始位置（最小差分の前方一致長）をローカル編集位置として記録。
    const cur = ytext.toString();
    let p = 0;
    const minLen = Math.min(cur.length, next.length);
    while (p < minLen && cur[p] === next[p]) p++;
    lastLocalEditAt = p;
    applyMinimalEdit(doc, ytext, next, LOCAL_ORIGIN);
  };
  const append = (chunk: string): void => {
    doc.transact(() => ytext.insert(ytext.length, chunk), LOCAL_ORIGIN);
  };
  const insertAt = (index: number, chunk: string): void => {
    const at = Math.max(0, Math.min(index, ytext.length));
    doc.transact(() => ytext.insert(at, chunk), LOCAL_ORIGIN);
  };
  const destroy = (): void => {
    ytext.unobserve(observer);
    provider.disconnect();
    doc.destroy();
  };

  // SFC 内で使う場合は自動破棄。テスト等のコンポーネント外では登録しない（警告回避）。
  if (getCurrentInstance()) onUnmounted(destroy);

  return { doc, ytext, text, conflictCount, setText, append, insertAt, destroy };
}
