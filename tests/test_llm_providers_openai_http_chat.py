from __future__ import annotations

import json
import threading
import time
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
    assert {"type": "tool", "name": "search", "summary": "searched vault: budget"} in events
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Found it."
    second = _Fake.seen[1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "RESULT(poltergeist_search,budget)"}
    assert second[1]["content"] == "earlier" and second[2]["content"] == "ok"   # history replayed after system


def test_chat_reuses_one_client_across_tool_rounds(server, monkeypatch):
    seen_clients: list[object] = []

    def _fake_call_tool(name, args, client=None):
        seen_clients.append(client)
        return f"RESULT({name})"

    monkeypatch.setattr(vault_tools, "call_tool", _fake_call_tool)
    _Fake.turns = [
        _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "poltergeist_search", "arguments": "{\"query\": \"a\"}"}}]}, "finish_reason": "tool_calls"}]}]),
        _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_2", "function": {"name": "poltergeist_search", "arguments": "{\"query\": \"b\"}"}}]}, "finish_reason": "tool_calls"}]}]),
        _sse([{"choices": [{"delta": {"content": "done"}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
    ]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c5")))
    assert events[-1]["type"] == "done"
    assert len(seen_clients) == 2
    assert seen_clients[0] is not None
    assert seen_clients[0] is seen_clients[1]


def test_chat_stops_promptly_when_cancelled_mid_stream():
    """A cancel_turn() call while blocked reading the next SSE chunk must
    interrupt the in-flight stream (not just skip it on the *next* loop
    check) and surface the same "stopped" shape the Claude/subprocess path
    uses (see stream.py's cancelled branch)."""
    first_sent = threading.Event()
    release = threading.Event()

    class _SlowFake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = f"data: {json.dumps({'choices': [{'delta': {'content': 'Hel'}}]})}\n\n".encode()
            self.wfile.write(chunk)
            self.wfile.flush()
            first_sent.set()
            # Simulate a stalled upstream: hold the connection open with no
            # further bytes until the test releases us.
            release.wait(5)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _SlowFake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    try:
        p = OpenAiHttp(base_url, "K", M); p._ollama = False
        events: list[dict] = []
        gen = p.chat(base.ChatRequest(prompt="hi", tier="fast", session_id=None, turn_key="cancel-1", timeout_s=30))

        def _drain():
            for e in gen:
                events.append(e)

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        assert first_sent.wait(2), "server never sent its first chunk"
        time.sleep(0.2)  # let the drain thread block on the next (stalled) read
        assert base.cancel_turn("cancel-1") is True
        t.join(timeout=3)
        assert not t.is_alive(), "chat() did not stop promptly after cancel_turn"
        assert events[-1] == {"type": "error", "message": "stopped", "interrupted": True}
    finally:
        release.set()
        httpd.shutdown()


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


# --- the stream always ends in a terminal event ---------------------------

def test_chat_skips_a_garbage_sse_line_and_still_finishes(server):
    """One unparsable SSE payload must not kill the turn: the renderer waits
    for a terminal event forever, and the partial reply is lost. Skip the line
    and keep streaming."""
    body = (
        f"data: {json.dumps({'choices': [{'delta': {'content': 'Hel'}}]})}\n\n"
        "data: {not json at all\n\n"
        f"data: {json.dumps({'choices': [{'delta': {'content': 'lo'}}]})}\n\n"
        "data: [DONE]\n\n"
    )
    _Fake.turns = [body]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="hi", tier="fast", session_id=None, turn_key="g1")))
    assert events[-1] == {"type": "done", "text": "Hello", "session_id": "g1"}


def test_chat_unparsable_tool_arguments_yield_an_error_event(server):
    _Fake.turns = [_sse([
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
            "name": "poltergeist_search", "arguments": "<<<not json>>>"}}]}, "finish_reason": "tool_calls"}]},
    ])]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="g2")))
    assert events[-1]["type"] == "error"
    assert "local model" in events[-1]["message"]


def test_chat_history_entry_without_text_does_not_kill_the_turn(server):
    _Fake.turns = [_sse([{"choices": [{"delta": {"content": "ok"}}]}])]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="g3",
                                          history=[{"role": "user"}])))
    assert events[-1]["type"] == "done"
    assert _Fake.seen[0]["messages"][1] == {"role": "user", "content": ""}
