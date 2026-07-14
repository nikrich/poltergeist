"""Router derives its destination enum and prompt from routing_config.

Drift note: the router enum is built dynamically by ``build_router_schema()``
(``ghostbrain/worker/router.py``) from ``projects_repo.active_destinations()``,
which in turn derives from ``routing_config.contexts()``. These tests exercise
that path end to end (configured contexts, no projects registered) rather than
the standalone ``router_json_schema()`` helper from the original task text,
which was dropped.
"""
from __future__ import annotations

from ghostbrain.worker import router as router_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_schema_enum_is_configured_contexts_plus_needs_review(vault):
    _configure(vault, ["alpha", "beta"])
    schema = router_mod.build_router_schema()
    assert schema["properties"]["context"]["enum"] == ["alpha", "beta", "needs_review"]


def test_llm_route_uses_configured_enum_and_injects_prompt(vault, monkeypatch):
    _configure(vault, ["alpha", "beta"])
    prompts = vault / "90-meta" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "router.md").write_text(
        "Contexts: {{contexts}}\n\n{{content}}", encoding="utf-8"
    )

    captured: dict = {}

    class FakeResult:
        def as_json(self):
            return {"context": "alpha", "confidence": 0.9, "reasoning": "r"}

    def fake_run(prompt, *, model, json_schema):
        captured["prompt"] = prompt
        captured["schema"] = json_schema
        return FakeResult()

    monkeypatch.setattr(router_mod.llm, "run", fake_run)

    decision = router_mod._route_via_llm({"id": "e1"}, "hello world", config={})

    assert decision.context == "alpha"
    assert "Contexts: alpha, beta" in captured["prompt"]
    assert captured["schema"] == router_mod.build_router_schema()
    assert captured["schema"]["properties"]["context"]["enum"] == [
        "alpha", "beta", "needs_review",
    ]
