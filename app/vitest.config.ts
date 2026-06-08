import { defineConfig } from "vitest/config";

// CRDT(メモ)層の純ロジック検証用。アプリの vite.config.ts（quasar/vue プラグイン）は読まず、
// node 環境で memoDoc を直接テストする（DD-013-2: 衝突0・CRC一致・遅延の機械検証）。
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
