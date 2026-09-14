from __future__ import annotations

from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.llm.providers import base


def _client():
    return TestClient(create_app("tok")), {"Authorization": "Bearer tok"}


def test_get_and_put_llm_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    (tmp_path / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: live\n")
    c, h = _client()
    assert c.get("/v1/settings/llm", headers=h).json()["provider"] == "claude"
    r = c.put(
        "/v1/settings/llm",
        json={"provider": "openai_http", "models": {"fast": "llama3.2"}, "base_url": "http://127.0.0.1:1234/v1"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["provider"] == "openai_http" and r.json()["effective_models"]["fast"] == "llama3.2"
    text = (tmp_path / "90-meta" / "config.yaml").read_text()
    assert "provider: openai_http" in text and "routing_mode: live" in text


def test_put_rejects_unknown_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    c, h = _client()
    assert c.put("/v1/settings/llm", json={"provider": "bard"}, headers=h).status_code == 422 or 400


def test_providers_route_probes_all(monkeypatch):
    from ghostbrain.api.routes import llm_providers as route

    monkeypatch.setattr(
        route,
        "_probe_all",
        lambda: {
            "claude": base.ProviderProbe(True, "2.1.0"),
            "codex": base.ProviderProbe(False, "not installed"),
            "gemini": base.ProviderProbe(False, "not installed"),
            "openai_http": base.ProviderProbe(False, "not answering", {"models": []}),
        },
    )
    monkeypatch.setattr(route, "_active", lambda: "claude")
    c, h = _client()
    body = c.get("/v1/llm/providers", headers=h).json()
    assert body["active"] == "claude" and body["providers"]["codex"]["ok"] is False and body["providers"]["openai_http"]["detail"]["models"] == []


def test_answer_returns_412_when_provider_unusable(monkeypatch):
    from ghostbrain.api.repo import answer as answer_repo
    from ghostbrain.api.repo.settings import ProviderUnavailable

    def gate():
        raise ProviderUnavailable("codex is not logged in; run `codex login`")

    monkeypatch.setattr(answer_repo, "require_provider", gate)
    c, h = _client()
    r = c.post("/v1/answer", json={"q": "hi"}, headers=h)
    assert r.status_code == 412 and "codex login" in r.json()["detail"]


def test_require_provider_caches_probe_for_60s(monkeypatch):
    from ghostbrain.api.repo import settings as settings_repo

    calls = {"n": 0}

    class FakeProvider:
        def probe(self):
            calls["n"] += 1
            return base.ProviderProbe(True, "ok")

    monkeypatch.setattr(settings_repo, "get_provider", lambda: FakeProvider())
    settings_repo._probe_cache.clear()
    settings_repo.require_provider()
    settings_repo.require_provider()
    assert calls["n"] == 1


def test_update_llm_settings_invalidates_probe_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    from ghostbrain.api.repo import settings as settings_repo

    calls = {"n": 0}

    class FakeProvider:
        def probe(self):
            calls["n"] += 1
            return base.ProviderProbe(True, "ok")

    monkeypatch.setattr(settings_repo, "get_provider", lambda: FakeProvider())
    settings_repo._probe_cache.clear()
    settings_repo.require_provider()
    settings_repo.update_llm_settings(provider="codex")
    settings_repo.require_provider()
    assert calls["n"] == 2
