"""Answer prompt's context sentence derives from routing_config.contexts()."""
from __future__ import annotations

from ghostbrain.api.repo import answer as answer_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_prompt_includes_configured_contexts(vault, monkeypatch):
    _configure(vault, ["alpha", "beta"])

    note = vault / "10-daily" / "2026-01-01.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: Test note\n---\nBody text.\n", encoding="utf-8")

    monkeypatch.setattr(
        answer_mod,
        "semantic_search",
        lambda q, limit: {
            "items": [{"path": "10-daily/2026-01-01.md", "score": 0.9}]
        },
    )

    captured: dict = {}

    class FakeResult:
        text = "An answer [1]."

    def fake_llm_run(prompt, *, model):
        captured["prompt"] = prompt
        return FakeResult()

    monkeypatch.setattr(answer_mod, "llm_run", fake_llm_run)

    result = answer_mod._answer("what's up", 8)

    assert "alpha, beta" in captured["prompt"]
    assert "sanlam" not in captured["prompt"]
    assert result["answer"] == "An answer [1]."
