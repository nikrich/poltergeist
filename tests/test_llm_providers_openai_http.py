from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.openai_http import OpenAiHttp


class _Fake(BaseHTTPRequestHandler):
    """Scripted OpenAI-compatible server. Set `script` per test."""
    script: dict = {}
    seen: list[dict] = []

    def log_message(self, *a): pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": m} for m in self.script.get("models", [])]})
        if self.path == "/api/tags":
            if self.script.get("ollama"):
                return self._send(200, {"models": [{"name": m} for m in self.script.get("models", [])]})
            return self._send(404, {})
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Fake.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if self.path == "/v1/chat/completions":
            return self._send(200, {"choices": [{"message": {"role": "assistant", "content": self.script["reply"]}}], "model": body.get("model")})
        if self.path == "/api/chat":
            return self._send(200, {"message": {"role": "assistant", "content": self.script["reply"]}, "model": body.get("model")})
        self._send(404, {})


@pytest.fixture
def server():
    _Fake.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


MODELS = {"fast": "llama3.2", "balanced": "qwen3", "quality": "qwen3"}


def test_complete_uses_chat_completions_with_system_and_json_schema(server):
    _Fake.script = {"reply": '{"ok": true}', "models": list(MODELS.values())}
    p = OpenAiHttp(server, "NOPE_KEY", MODELS)
    out = p.complete(base.CompletionRequest(prompt="hi", tier="fast", system_prompt="be terse",
                                            json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}}))
    assert out.structured == {"ok": True} and out.model == "llama3.2" and out.cost_usd == 0
    req = _Fake.seen[-1]
    assert req["path"] == "/v1/chat/completions" and req["auth"] is None   # localhost: no key sent
    assert req["body"]["messages"][0] == {"role": "system", "content": "be terse"}
    assert req["body"]["response_format"]["type"] == "json_schema"


def test_ollama_uses_api_chat_with_format(server):
    _Fake.script = {"reply": '{"a": 1}', "models": ["qwen3"], "ollama": True}
    p = OpenAiHttp(server, "K", {"fast": "qwen3", "balanced": "qwen3", "quality": "qwen3"})
    out = p.complete(base.CompletionRequest(prompt="p", tier="fast", json_schema={"type": "object"}))
    assert out.structured == {"a": 1}
    assert _Fake.seen[-1]["path"] == "/api/chat" and _Fake.seen[-1]["body"]["format"] == {"type": "object"}


def test_non_localhost_sends_bearer_from_env(monkeypatch, server):
    _Fake.script = {"reply": "x", "models": ["m"]}
    monkeypatch.setenv("MY_KEY", "sk-test")
    p = OpenAiHttp(server.replace("127.0.0.1", "localhost"), "MY_KEY", {"fast": "m", "balanced": "m", "quality": "m"})
    p._is_local = lambda: False  # type: ignore[attr-defined]
    p.complete(base.CompletionRequest(prompt="p", tier="fast"))
    assert _Fake.seen[-1]["auth"] == "Bearer sk-test"


def test_missing_tier_model_is_llm_error(server):
    p = OpenAiHttp(server, "K", {"fast": "m"})
    with pytest.raises(LLMError, match="balanced"):
        p.complete(base.CompletionRequest(prompt="p", tier="balanced"))


def test_probe_lists_models_and_requires_all_tiers(server):
    _Fake.script = {"models": ["llama3.2", "qwen3"]}
    assert OpenAiHttp(server, "K", MODELS).probe().ok is True
    bad = OpenAiHttp(server, "K", {"fast": "llama3.2"}).probe()
    assert bad.ok is False and "balanced" in bad.reason and bad.detail["models"] == ["llama3.2", "qwen3"]
    down = OpenAiHttp("http://127.0.0.1:9/v1", "K", MODELS).probe()
    assert down.ok is False and "not answering" in down.reason


def test_probe_fails_when_server_lists_no_models(server):
    _Fake.script = {"models": []}
    bad = OpenAiHttp(server, "K", MODELS).probe()
    assert bad.ok is False and "lists no models" in bad.reason and bad.detail["models"] == []


def test_image_paths_become_data_url_parts(server, tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(b"\x89PNG\r\n\x1a\n")
    _Fake.script = {"reply": "seen", "models": list(MODELS.values())}
    OpenAiHttp(server, "K", MODELS).complete(base.CompletionRequest(prompt="describe", tier="fast", image_paths=[str(img)]))
    content = _Fake.seen[-1]["body"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_probe_against_a_server_that_answers_html_is_not_ok():
    """A proxy or captive portal answering 200 text/html made r.json() raise a
    JSONDecodeError straight out of probe(), which is not an httpx.HTTPError —
    the doctor check and the settings panel both saw an exception, not a row."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from ghostbrain.llm.providers.openai_http import OpenAiHttp

    class _Html(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            body = b"<html><body>hello</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Html)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
        probe = OpenAiHttp(url, "K", {"fast": "m", "balanced": "m", "quality": "m"}).probe()
        assert probe.ok is False
        assert "JSON" in probe.reason
    finally:
        httpd.shutdown()
