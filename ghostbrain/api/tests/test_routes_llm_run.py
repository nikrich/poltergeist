"""POST /v1/llm/run — raw prompt runner for plugins."""
from ghostbrain.llm.client import LLMError, LLMResult


def _result(text="hi", structured=None):
    return LLMResult(text=text, structured=structured, model="sonnet",
                     cost_usd=0.01, duration_ms=1200, session_id="s", raw={})


def test_llm_run_success(client, auth_headers, monkeypatch):
    seen = {}

    def fake_run(prompt, **kw):
        seen["prompt"], seen["kw"] = prompt, kw
        return _result(text="pong")

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", headers=auth_headers, json={"prompt": "ping", "system": "be brief", "model": "opus"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "pong" and body["error"] is None
    assert body["costUsd"] == 0.01 and body["durationMs"] == 1200
    assert seen["prompt"] == "ping"
    assert seen["kw"]["system_prompt"] == "be brief"
    assert seen["kw"]["model"] == "opus"
    assert seen["kw"]["timeout_s"] == 600


def test_llm_run_json_schema_passthrough(client, auth_headers, monkeypatch):
    schema = {"type": "object", "properties": {"x": {"type": "number"}}}

    def fake_run(prompt, **kw):
        assert kw["json_schema"] == schema
        return _result(text='{"x": 1}', structured={"x": 1})

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", headers=auth_headers, json={"prompt": "p", "jsonSchema": schema})
    assert r.json()["structured"] == {"x": 1}


def test_llm_run_error_is_structured(client, auth_headers, monkeypatch):
    def fake_run(prompt, **kw):
        raise LLMError("claude binary not found")

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", headers=auth_headers, json={"prompt": "p"})
    assert r.status_code == 200
    assert r.json()["error"] == "LLMError: claude binary not found"
    assert r.json()["text"] == ""


def test_llm_run_empty_prompt_422(client, auth_headers):
    assert client.post("/v1/llm/run", headers=auth_headers, json={"prompt": "  "}).status_code == 422
