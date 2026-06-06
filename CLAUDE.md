# SynchroniNote プロジェクト設定

リアルタイムAI協調型ローカル議事録システム『SynchroniNote（シンクロニ・ノート）』。
このファイルは DD-Know-How をベースにした Claude Code 設定です。

## DD設定

- **DDフォルダ**: `doc/DD/`
- **アーカイブ**: `doc/archived/DD/`
- **テンプレート**: `doc/templates/dd_template.md`
- **インデックス**: `doc/DD/DD-INDEX.md`

## 利用可能なスキル

> スキルは `.claude/skills/` に配置されています（skills形式）

### DD管理
- `/dd new タイトル` - 新規DD作成
- `/dd list` - DD一覧
- `/dd log メモ` - ログ追記
- `/dd archive 番号` - アーカイブ
- `/dd search キーワード` - DD検索
- `/dd rebuild-index` - インデックス再構築
- DA メソッド: `doc/da-method.md`（DA品質フィルター・再チェック条件）

## 開発フロー

詳細は `doc/development-flow.md`（5ステップ）を参照。

## プロジェクト固有の設定

### 技術スタック
- コア: Rust（低遅延・並列パイプライン処理）
- 動作環境: Windows 11 / GPUなし（CPU駆動）/ RAM 50GB
- AI: ローカル実行（話者識別・STT・LLM要約）— クラウド送信なし（完全オフライン）
- エディタ: 人間×AI リアルタイム協調エディタ（分散同期アルゴリズム）

### コーディング規約
- 詳細: `doc/templates/coding-standards.md`（コーディング基準書）
- コードレビュー時はこの基準書に基づいて評価する

### テスト方針
-（未定）

### セキュリティ要件
- 機密情報の外部送信禁止。AI処理は完全ローカルで完結すること。
