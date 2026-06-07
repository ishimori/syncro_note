"""モデル切替（DD-006 / model_switch.py）の順序保証とロバスト性を Ollama 非依存で検証する。"""

from __future__ import annotations

import types

from synchroni_note.pipeline import model_switch


def test_loaded_model_names_empty_on_ps_failure(monkeypatch) -> None:
    def boom() -> None:
        raise RuntimeError("ollama down")

    monkeypatch.setattr(model_switch.ollama, "ps", boom)
    assert model_switch.loaded_model_names() == []


def test_loaded_model_names_parses_model_attr(monkeypatch) -> None:
    fake = types.SimpleNamespace(
        models=[types.SimpleNamespace(model="qwen3:8b"), types.SimpleNamespace(model="gemma4:26b")]
    )
    monkeypatch.setattr(model_switch.ollama, "ps", lambda: fake)
    assert model_switch.loaded_model_names() == ["qwen3:8b", "gemma4:26b"]


def test_wait_until_unloaded_true_when_already_gone(monkeypatch) -> None:
    monkeypatch.setattr(model_switch, "loaded_model_names", lambda: [])
    assert model_switch.wait_until_unloaded("qwen3:8b") is True


def test_wait_until_unloaded_times_out(monkeypatch) -> None:
    # まだロード中のまま。偽クロックで実時間に依存させずタイムアウトさせる。
    monkeypatch.setattr(model_switch, "loaded_model_names", lambda: ["qwen3:8b"])
    ticks = iter([0.0, 0.0, 0.1, 0.2, 0.3])  # deadline=0+0.25 を超える

    def clock() -> float:
        return next(ticks)

    ok = model_switch.wait_until_unloaded(
        "qwen3:8b", timeout_s=0.25, poll_s=0.05, sleep=lambda _s: None, clock=clock
    )
    assert ok is False


def test_switch_to_batch_unloads_then_loads(monkeypatch) -> None:
    # live が載っている → 退避要求 → 消失確認 → batch ロードへ、の順で通知される。
    calls = {"n": 0}

    def fake_loaded() -> list[str]:
        calls["n"] += 1
        return ["qwen3:8b"] if calls["n"] == 1 else []  # 1回目だけ載っている

    unloaded: list[str] = []
    monkeypatch.setattr(model_switch, "loaded_model_names", fake_loaded)
    monkeypatch.setattr(model_switch, "unload_model", lambda m: unloaded.append(m))

    stages: list[tuple[str, str]] = []
    ok = model_switch.switch_to_batch(
        "qwen3:8b", "gemma4:26b", on_status=lambda s, m: stages.append((s, m))
    )

    assert ok is True
    assert unloaded == ["qwen3:8b"]
    assert stages == [
        ("unloading", "qwen3:8b"),
        ("unloaded", "qwen3:8b"),
        ("loading_batch", "gemma4:26b"),
    ]


def test_switch_to_batch_skips_when_already_free(monkeypatch) -> None:
    monkeypatch.setattr(model_switch, "loaded_model_names", lambda: [])
    called: list[str] = []
    monkeypatch.setattr(model_switch, "unload_model", lambda m: called.append(m))

    stages: list[tuple[str, str]] = []
    ok = model_switch.switch_to_batch(
        "qwen3:8b", "gemma4:26b", on_status=lambda s, m: stages.append((s, m))
    )

    assert ok is True
    assert called == []  # 退避要求は出さない
    assert stages == [("already_free", "qwen3:8b"), ("loading_batch", "gemma4:26b")]
