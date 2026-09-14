from __future__ import annotations

import pytest
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
    r = c.put("/v1/settings/llm", json={"provider": "bard"}, headers=h)
    assert r.status_code in (400, 422)
    assert "bard" in r.text


def test_update_llm_settings_rejects_unknown_provider_directly(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    from ghostbrain.api.repo.settings import update_llm_settings

    with pytest.raises(ValueError, match="bard"):
        update_llm_settings(provider="bard")


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


def test_providers_route_degrades_when_one_provider_raises(monkeypatch):
    """A provider adapter raising something other than LLMError (e.g. a bug in
    its constructor) must not break the whole /v1/llm/providers response —
    only that provider's entry should report unavailable."""
    from ghostbrain.api.routes import llm_providers as route

    class WorkingProvider:
        def probe(self):
            return base.ProviderProbe(True, "ok")

    def fake_get_provider(cfg):
        if cfg.provider == "codex":
            raise TypeError("boom")
        return WorkingProvider()

    monkeypatch.setattr(route, "get_provider", fake_get_provider)
    c, h = _client()
    body = c.get("/v1/llm/providers", headers=h).json()
    assert set(body["providers"]) == {"claude", "codex", "gemini", "openai_http"}
    assert body["providers"]["codex"]["ok"] is False
    assert "boom" in body["providers"]["codex"]["reason"]
    assert body["providers"]["claude"]["ok"] is True


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


def test_switching_provider_clears_the_model_overrides(tmp_path, monkeypatch):
    """llm.models is a single global namespace, and the settings panel writes it
    from the local-only tier pickers. Leaving `qwen3` behind after a switch back
    to claude would run `claude --model qwen3`, so a provider change drops the
    overrides."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    c, h = _client()
    c.put("/v1/settings/llm",
          json={"provider": "openai_http", "models": {"fast": "qwen3", "balanced": "qwen3", "quality": "qwen3"}},
          headers=h)
    body = c.put("/v1/settings/llm", json={"provider": "claude"}, headers=h).json()
    assert body["models"] == {"fast": None, "balanced": None, "quality": None}
    assert body["effective_models"] == {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}
    assert "qwen3" not in (tmp_path / "90-meta" / "config.yaml").read_text()


def test_setting_the_same_provider_keeps_the_model_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    c, h = _client()
    c.put("/v1/settings/llm", json={"provider": "openai_http", "models": {"fast": "qwen3"}}, headers=h)
    body = c.put("/v1/settings/llm", json={"provider": "openai_http"}, headers=h).json()
    assert body["models"]["fast"] == "qwen3"


def test_switching_provider_and_models_together_keeps_the_new_models(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    c, h = _client()
    c.put("/v1/settings/llm", json={"provider": "claude", "models": {"fast": "haiku"}}, headers=h)
    body = c.put("/v1/settings/llm",
                 json={"provider": "openai_http", "models": {"fast": "qwen3"}}, headers=h).json()
    assert body["models"] == {"fast": "qwen3", "balanced": None, "quality": None}
