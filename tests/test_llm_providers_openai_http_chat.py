from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ghostbrain.llm.providers import base, vault_tools
from ghostbrain.llm.providers.openai_http import OpenAiHttp


def _sse(chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


class _Fake(BaseHTTPRequestHandler):
    turns: list[str] = []      # scripted SSE bodies, consumed in order
    seen: list[dict] = []
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n))
        _Fake.seen.append(body)
        data = _Fake.turns.pop(0).encode()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


@pytest.fixture
def server():
    _Fake.seen = []; _Fake.turns = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


M = {"fast": "m", "balanced": "m", "quality": "m"}


def test_chat_streams_text_then_done(server):
    _Fake.turns = [_sse([
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="hi", tier="balanced", session_id=None, turn_key="c1", system_prompt="sys")))
    assert events[0] == {"type": "session", "session_id": "c1"}
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Hel", "lo"]
    assert events[-1] == {"type": "done", "text": "Hello", "session_id": "c1"}
    body = _Fake.seen[0]
    assert body["stream"] is True and body["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in body["tools"]} == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}


def test_chat_runs_a_tool_round_and_feeds_the_result_back(server, monkeypatch):
    monkeypatch.setattr(vault_tools, "call_tool", lambda name, args, client=None: f"RESULT({name},{args['query']})")
    _Fake.turns = [
        _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "poltergeist_search", "arguments": "{\"query\": \"budget\"}"}}]}, "finish_reason": "tool_calls"}]}]),
        _sse([{"choices": [{"delta": {"content": "Found it."}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
    ]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c2",
                                          history=[{"role": "user", "text": "earlier"}, {"role": "assistant", "text": "ok"}])))
    assert {"type": "tool", "name": "poltergeist_search", "summary": "searched vault: budget"} in events
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Found it."
    second = _Fake.seen[1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "RESULT(poltergeist_search,budget)"}
    assert second[1]["content"] == "earlier" and second[2]["content"] == "ok"   # history replayed after system


def test_chat_gives_up_after_max_rounds(server, monkeypatch):
    monkeypatch.setattr(vault_tools, "call_tool", lambda *a, **k: "r")
    call = _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "poltergeist_ask", "arguments": "{\"question\":\"?\"}"}}]}, "finish_reason": "tool_calls"}]}])
    _Fake.turns = [call] * (vault_tools.MAX_TOOL_ROUNDS + 1)
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c3")))
    assert events[-1]["type"] == "error" and "tool rounds" in events[-1]["message"]


def test_chat_http_failure_is_error_event(server):
    p = OpenAiHttp("http://127.0.0.1:9/v1", "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c4")))
    assert events[-1]["type"] == "error"
