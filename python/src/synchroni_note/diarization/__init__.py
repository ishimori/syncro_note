"""話者分離(diarization)PoC（DD-004）。

評価期(Python/CPU)で「whisper非依存の話者分離」を手法比較するためのハーネス。
- base: 手法共通の Turn 型と diarize I/F、疎通用 dummy 実装
- reference: 正解ターン(話者ラベル付き) + whisper word timestamps から参照RTTMを自動生成
- rttm: RTTM 入出力と DER(話者分離誤り率)計測（自前実装・collar対応）
"""
