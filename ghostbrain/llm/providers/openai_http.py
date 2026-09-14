"""Local / OpenAI-compatible HTTP adapter (Ollama, LM Studio, OpenRouter-style endpoints)."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ghostbrain.llm.client import LLMError, LLMResult, LLMTimeout, _parse_json_tolerant
from ghostbrain.llm.providers import base

log = logging.getLogger("ghostbrain.llm.providers.openai_http")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class OpenAiHttp:
    id = "openai_http"

    def __init__(self, base_url: str, api_key_env: str, models: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self._models = dict(models)
        self._ollama: bool | None = None

    # -- helpers ---------------------------------------------------------------
    def models(self) -> dict[str, str]:
        return dict(self._models)

    def _origin(self) -> str:
        u = urlparse(self.base_url)
        return f"{u.scheme}://{u.netloc}"

    def _is_local(self) -> bool:
        return (urlparse(self.base_url).hostname or "") in LOCAL_HOSTS

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if not self._is_local():
            key = os.environ.get(self.api_key_env, "")
            if key:
                h["Authorization"] = f"Bearer {key}"
        return h

    def is_ollama(self) -> bool:
        if self._ollama is None:
            try:
                r = httpx.get(f"{self._origin()}/api/tags", timeout=3.0)
                self._ollama = r.status_code == 200
            except httpx.HTTPError:
                self._ollama = False
        return self._ollama

    def _model_for(self, tier: str) -> str:
        model = self._models.get(tier)
        if not model:
            raise LLMError(f"openai_http: no model configured for the {tier} tier — set llm.models.{tier} in config.yaml")
        return model

    def build_messages(self, req: base.CompletionRequest) -> list[dict]:
        msgs: list[dict] = []
        if req.system_prompt:
            msgs.append({"role": "system", "content": req.system_prompt})
        if req.image_paths:
            parts: list[dict] = [{"type": "text", "text": req.prompt}]
            for p in req.image_paths:
                mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
                data = base64.b64encode(Path(p).read_bytes()).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append({"role": "user", "content": req.prompt})
        return msgs

    # -- batch -----------------------------------------------------------------
    def complete(self, req: base.CompletionRequest) -> LLMResult:
        model = self._model_for(req.tier)
        messages = self.build_messages(req)
        started = time.monotonic()
        try:
            if self.is_ollama():
                body: dict = {"model": model, "messages": messages, "stream": False}
                if req.json_schema is not None:
                    body["format"] = req.json_schema
                r = httpx.post(f"{self._origin()}/api/chat", json=body, headers=self._headers(), timeout=req.timeout_s)
                r.raise_for_status()
                text = (r.json().get("message") or {}).get("content") or ""
            else:
                body = {"model": model, "messages": messages, "stream": False}
                if req.json_schema is not None:
                    body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": req.json_schema}}
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers(), timeout=req.timeout_s)
                r.raise_for_status()
                text = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"openai_http: timed out after {req.timeout_s}s") from e
        except httpx.HTTPError as e:
            raise LLMError(f"openai_http: {e}") from e
        structured = _parse_json_tolerant(text) if req.json_schema is not None else None
        return LLMResult(text=text, structured=structured, model=model, cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id="", raw={"body": body})

    def probe(self) -> base.ProviderProbe:
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=3.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            return base.ProviderProbe(False, f"{self.base_url} is not answering ({e.__class__.__name__}); start Ollama or LM Studio, or fix llm.openai_http.base_url", {"base_url": self.base_url})
        try:
            listed = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        except Exception:  # noqa: BLE001 — a proxy or captive portal answering
            # 200 text/html raises out of r.json(); that is a failed probe to
            # report, not an exception for the doctor check to trip over.
            return base.ProviderProbe(False, f"{self.base_url}/models did not return JSON; check llm.openai_http.base_url points at an OpenAI-compatible server", {"base_url": self.base_url})
        missing = [t for t in base.TIERS if not self._models.get(t)]
        if missing:
            return base.ProviderProbe(False, f"no model set for tier(s): {', '.join(missing)} — pick them in Settings → AI provider", {"base_url": self.base_url, "models": listed})
        if not listed:
            return base.ProviderProbe(False, f"{self.base_url} lists no models; pull or load one (e.g. `ollama pull qwen3`) and pick it in Settings → AI provider", {"base_url": self.base_url, "models": []})
        absent = [m for m in self._models.values() if m not in listed]
        if absent:
            return base.ProviderProbe(False, f"model(s) not installed on the server: {', '.join(sorted(set(absent)))}", {"base_url": self.base_url, "models": listed})
        return base.ProviderProbe(True, f"{self.base_url} ({'ollama' if self.is_ollama() else 'openai-compatible'})", {"base_url": self.base_url, "models": listed, "tiers": self.models()})

    # -- chat --------------------------------------------------------------
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT
        from ghostbrain.llm.providers import vault_tools
        from ghostbrain.mcp.client import SidecarClient

        sid = req.session_id or req.turn_key or "local"
        yield {"type": "session", "session_id": sid}
        try:
            model = self._model_for(req.tier)
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return
        messages: list[dict] = [{"role": "system", "content": req.system_prompt or CHAT_SYSTEM_PROMPT}]
        for m in req.history or []:
            messages.append({"role": m["role"], "content": m.get("text", "")})
        messages.append({"role": "user", "content": req.prompt})

        cancelled = threading.Event()
        # Holds the live httpx.Response for whichever round is currently
        # streaming, so `kill` (invoked by base.cancel_turn from another
        # thread) can close the socket and unblock a read that's stalled
        # waiting on the next chunk — checking `cancelled` only between
        # rounds isn't enough, since a generator suspended at `yield` inside
        # a blocking socket read won't see it until the read itself returns.
        response_cell: dict[str, httpx.Response | None] = {"response": None}

        def _kill() -> None:
            resp = response_cell["response"]
            if resp is None:
                return
            # resp.close() alone does NOT interrupt a read already blocked
            # on the socket in the streaming thread (verified empirically —
            # it just waits out the normal timeout); shutting down the raw
            # socket first reliably wakes a blocked recv() cross-thread.
            # network_stream/_sock are private httpcore/stdlib internals, so
            # this degrades to a plain close() if either is unavailable.
            sock = getattr(resp.extensions.get("network_stream"), "_sock", None)
            if isinstance(sock, socket.socket):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # already closed/not connected
            resp.close()

        if req.turn_key:
            base.register_turn(req.turn_key, cancelled=cancelled, kill=_kill)
        full: list[str] = []
        client = SidecarClient()
        try:
            for _round in range(vault_tools.MAX_TOOL_ROUNDS + 1):
                if cancelled.is_set():
                    yield {"type": "error", "message": "stopped", "interrupted": True}
                    return
                if _round == vault_tools.MAX_TOOL_ROUNDS:
                    yield {"type": "error", "message": f"gave up after {vault_tools.MAX_TOOL_ROUNDS} tool rounds"}
                    return
                text, calls = yield from self._stream_once(model, messages, req.timeout_s, cancelled, response_cell, full)
                if cancelled.is_set():
                    yield {"type": "error", "message": "stopped", "interrupted": True}
                    return
                if not calls:
                    yield {"type": "done", "text": "".join(full), "session_id": sid}
                    return
                messages.append(self._assistant_message(text, calls))
                for c in calls:
                    args = _parse_json_tolerant(c["function"]["arguments"] or "{}")
                    yield {"type": "tool", "name": vault_tools.short_name_for(c["function"]["name"]),
                           "summary": vault_tools.summary_for(c["function"]["name"], args)}
                    result = vault_tools.call_tool(c["function"]["name"], args, client=client)
                    if cancelled.is_set():
                        yield {"type": "error", "message": "stopped", "interrupted": True}
                        return
                    messages.append(self._tool_message(c, result))
        except Exception as e:  # noqa: BLE001 — this generator OWNS the turn's
            # terminal event: anything escaping here (a JSONDecodeError from a
            # bad SSE line, an LLMError from garbage tool arguments, an OSError
            # from the cancel path's socket shutdown) would end the stream with
            # no done/error at all, hanging the renderer and losing the partial
            # reply. Every failure becomes a terminal error event instead.
            if cancelled.is_set():
                yield {"type": "error", "message": "stopped", "interrupted": True}
            else:
                log.warning("local chat turn failed", exc_info=True)
                yield {"type": "error", "message": f"local model: {e}"}
        finally:
            client.close()
            if req.turn_key:
                base.unregister_turn(req.turn_key)

    # -- conversation shapes ---------------------------------------------
    # Internally a tool call always looks like OpenAI's: an id, a name, and
    # `arguments` as a JSON *string*. Ollama's /api/chat wants neither the id
    # nor the string — it takes `arguments` as an object and matches tool
    # results positionally — so the two helpers below convert on the way back
    # out, leaving one shape for the rest of the loop to reason about.

    def _assistant_message(self, text: str, calls: list[dict]) -> dict:
        if not self.is_ollama():
            return {"role": "assistant", "content": text or None, "tool_calls": calls}
        out = []
        for c in calls:
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            out.append({"function": {"name": c["function"]["name"], "arguments": args}})
        return {"role": "assistant", "content": text or "", "tool_calls": out}

    def _tool_message(self, call: dict, result: str) -> dict:
        if self.is_ollama():
            return {"role": "tool", "content": result}
        return {"role": "tool", "tool_call_id": call["id"], "content": result}

    def _stream_once(self, model, messages, timeout_s, cancelled, response_cell, full):
        """Stream one completion. Yields delta events; returns (text, tool_calls)."""
        if self.is_ollama():
            return (yield from self._stream_ollama_once(model, messages, timeout_s, cancelled, response_cell, full))
        return (yield from self._stream_openai_once(model, messages, timeout_s, cancelled, response_cell, full))

    def _stream_ollama_once(self, model, messages, timeout_s, cancelled, response_cell, full):
        """One round against Ollama's native /api/chat (NDJSON).

        The OpenAI-compat shim Ollama also serves does not stream tool calls
        reliably; /api/chat is the endpoint the spec picks for this driver.
        Each line is a whole message delta — `{"message": {...}, "done": bool}`
        — rather than an SSE `data:` frame, and its tool-call `arguments` are
        already an object. Normalised here into the same (text, tool_calls)
        shape the OpenAI path returns.
        """
        from ghostbrain.llm.providers import vault_tools

        body = {"model": model, "messages": messages, "stream": True, "tools": vault_tools.TOOL_SCHEMAS}
        url = f"{self._origin()}/api/chat"
        text_parts: list[str] = []
        calls: list[dict] = []
        with httpx.stream("POST", url, json=body, headers=self._headers(), timeout=timeout_s) as r:
            response_cell["response"] = r
            try:
                r.raise_for_status()
                for line in r.iter_lines():
                    if cancelled.is_set():
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        log.debug("skipping unparsable NDJSON line: %.200s", line)
                        continue
                    msg = ev.get("message") or {}
                    content = msg.get("content")
                    if content:
                        text_parts.append(content)
                        full.append(content)
                        yield {"type": "delta", "text": content}
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        args = fn.get("arguments")
                        calls.append({
                            "id": tc.get("id") or f"call_{len(calls) + 1}",
                            "type": "function",
                            "function": {
                                "name": str(fn.get("name") or ""),
                                "arguments": args if isinstance(args, str) else json.dumps(args or {}),
                            },
                        })
                    if ev.get("done"):
                        break
            finally:
                response_cell["response"] = None
        return "".join(text_parts), calls

    def _stream_openai_once(self, model, messages, timeout_s, cancelled, response_cell, full):
        """One round against an OpenAI-compatible /chat/completions (SSE)."""
        from ghostbrain.llm.providers import vault_tools

        body = {"model": model, "messages": messages, "stream": True, "tools": vault_tools.TOOL_SCHEMAS}
        url = f"{self.base_url}/chat/completions"
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        with httpx.stream("POST", url, json=body, headers=self._headers(), timeout=timeout_s) as r:
            response_cell["response"] = r
            try:
                r.raise_for_status()
                for line in r.iter_lines():
                    if cancelled.is_set():
                        break
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        # One malformed line is not worth losing the turn over:
                        # local servers truncate and interleave under load.
                        log.debug("skipping unparsable SSE payload: %.200s", payload)
                        continue
                    delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        full.append(delta["content"])
                        yield {"type": "delta", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": tc.get("id", ""), "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        slot["function"]["arguments"] += fn.get("arguments") or ""
            finally:
                response_cell["response"] = None
        return "".join(text_parts), [calls[i] for i in sorted(calls)]
