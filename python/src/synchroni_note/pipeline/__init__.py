"""バッチMVP パイプライン: 音声ファイル → 文字起こし → ケバ取り → 要約 → 議事録Markdown。

DD-008。評価期（Python）の中核価値。設計SSOT（doc/spec/基本設計書.md）に準拠:
VAD必須（無音幻覚抑制）/ STTは medium / 要約はバッチLLM（gemma4:26b）。
"""
