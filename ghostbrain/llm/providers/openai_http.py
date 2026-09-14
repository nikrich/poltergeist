"""Local / OpenAI-compatible HTTP adapter (Ollama, LM Studio, OpenRouter-style endpoints)."""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
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
            listed = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        except httpx.HTTPError as e:
            return base.ProviderProbe(False, f"{self.base_url} is not answering ({e.__class__.__name__}); start Ollama or LM Studio, or fix llm.openai_http.base_url", {"base_url": self.base_url})
        missing = [t for t in base.TIERS if not self._models.get(t)]
        if missing:
            return base.ProviderProbe(False, f"no model set for tier(s): {', '.join(missing)} — pick them in Settings → AI provider", {"base_url": self.base_url, "models": listed})
        absent = [m for m in self._models.values() if listed and m not in listed]
        if absent:
            return base.ProviderProbe(False, f"model(s) not installed on the server: {', '.join(sorted(set(absent)))}", {"base_url": self.base_url, "models": listed})
        return base.ProviderProbe(True, f"{self.base_url} ({'ollama' if self.is_ollama() else 'openai-compatible'})", {"base_url": self.base_url, "models": listed, "tiers": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        raise LLMError("openai_http chat lands in Task 5")
