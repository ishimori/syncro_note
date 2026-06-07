"""ライブ整形モデル(qwen3:8b) → 終了後バッチ清書モデル(gemma4:26b) の安全な切替（DD-006）。

切替方式（基本設計書 §4.3）: ``keep_alive=0`` で退避 → ``ollama.ps()`` で空確認 → batch ロード。
**batch をロードする前に live の消失を待つ**ことで、二重常駐（メモリ二重確保）を構造的に防ぐ。

`bench/model_switch_bench.py` の実測ロジックを製品コードへ昇格したもの（bench はベンチ専用のまま）。
Ollama を叩く薄い関数群と、純粋な待機ループに分け、テストではモンキーパッチで差し替えられる。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import ollama

DEFAULT_UNLOAD_TIMEOUT_S = 30.0  # live がこの秒数で消えなければ切替失敗扱い
DEFAULT_POLL_S = 0.2  # 退避（消失）待ちのポーリング間隔

# 切替の段階通知コールバック型: (stage, model) を受け取り UI などへ流す。
StatusCallback = Callable[[str, str], None]


def loaded_model_names() -> list[str]:
    """現在 Ollama にロードされているモデル名一覧（取得失敗時は空）。"""
    try:
        resp = ollama.ps()
    except Exception:
        return []
    names: list[str] = []
    for m in resp.models:
        name = getattr(m, "model", None) or getattr(m, "name", None)
        if name:
            names.append(name)
    return names


def unload_model(model: str) -> None:
    """``keep_alive=0`` の空生成で退避要求する（失敗は無視＝既に未ロード等）。"""
    try:
        ollama.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def wait_until_unloaded(
    model: str,
    *,
    timeout_s: float = DEFAULT_UNLOAD_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> bool:
    """``model`` が ps から消えるまで待つ。消えたら True、タイムアウトなら False。

    ``sleep``/``clock`` を差し替え可能にし、テストを実時間に依存させない。
    """
    deadline = clock() + timeout_s
    while clock() < deadline:
        if model not in loaded_model_names():
            return True
        sleep(poll_s)
    return model not in loaded_model_names()


def switch_to_batch(
    live_model: str,
    batch_model: str,
    *,
    on_status: StatusCallback | None = None,
    timeout_s: float = DEFAULT_UNLOAD_TIMEOUT_S,
) -> bool:
    """live を退避し、消失を確認してから batch 投入の準備を整える。

    batch のロード自体は呼び出し側の生成（最初のトークン）で起きる。本関数は「live を確実に
    どけてから batch へ進む」順序保証のみを担い、二重常駐を避ける。

    返り値: 切替準備が整えば True（live がもともと未ロード／退避成功）、退避が時間内に
    終わらなければ False。``on_status`` には段階名を通知する:
    ``unloading`` → ``unloaded`` | ``unload_timeout`` / ``already_free`` → ``loading_batch``。
    """

    def notify(stage: str, model: str) -> None:
        if on_status is not None:
            on_status(stage, model)

    ok = True
    if live_model in loaded_model_names():
        notify("unloading", live_model)
        unload_model(live_model)
        ok = wait_until_unloaded(live_model, timeout_s=timeout_s)
        notify("unloaded" if ok else "unload_timeout", live_model)
    else:
        notify("already_free", live_model)

    notify("loading_batch", batch_model)
    return ok
