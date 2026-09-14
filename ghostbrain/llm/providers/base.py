"""Provider protocol, request/response types, tiers, and the shared turn registry.

A provider turns a CompletionRequest into an LLMResult (batch) or a ChatRequest
into the renderer's event stream (chat). Model choice is a *tier*; each provider
maps tiers to its own model names. The old Claude aliases are accepted as tier
synonyms so existing config.yaml keys keep working.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ghostbrain.llm.client import LLMError, LLMResult

Tier = Literal["fast", "balanced", "quality"]
TIERS: tuple[str, ...] = ("fast", "balanced", "quality")
ALIASES: dict[str, str] = {"haiku": "fast", "sonnet": "balanced", "opus": "quality"}


def to_tier(model: str) -> Tier:
    name = (model or "").strip().lower()
    if name in TIERS:
        return name  # type: ignore[return-value]
    if name in ALIASES:
        return ALIASES[name]  # type: ignore[return-value]
    raise LLMError(
        f"unknown model tier {model!r}: use fast | balanced | quality "
        f"(or the aliases haiku | sonnet | opus)"
    )


@dataclass
class CompletionRequest:
    prompt: str
    tier: Tier
    json_schema: dict | None = None
    system_prompt: str | None = None
    image_paths: list[str] | None = None
    timeout_s: int = 120
    budget_usd: float | None = None


@dataclass
class ChatRequest:
    prompt: str
    tier: Tier
    session_id: str | None
    turn_key: str | None
    system_prompt: str | None = None
    user_servers: list[dict] = field(default_factory=list)
    history: list[dict] | None = None
    timeout_s: int = 300
    allowed_tools: str | None = None


@dataclass
class ProviderProbe:
    ok: bool
    reason: str
    detail: dict = field(default_factory=dict)


class Provider(Protocol):
    id: str

    def models(self) -> dict[str, str]: ...
    def complete(self, req: CompletionRequest) -> LLMResult: ...
    def chat(self, req: ChatRequest) -> Iterator[dict]: ...
    def probe(self) -> ProviderProbe: ...


# --- running-turn registry (shared by every chat driver) ---------------------

@dataclass
class _RunningTurn:
    cancelled: threading.Event
    kill: Callable[[], None]


_lock = threading.Lock()
_running: dict[str, _RunningTurn] = {}


def register_turn(key: str, *, cancelled: threading.Event, kill: Callable[[], None]) -> None:
    with _lock:
        _running[key] = _RunningTurn(cancelled=cancelled, kill=kill)


def unregister_turn(key: str) -> None:
    with _lock:
        _running.pop(key, None)


def cancel_turn(key: str) -> bool:
    with _lock:
        entry = _running.pop(key, None)
    if entry is None:
        return False
    entry.cancelled.set()
    entry.kill()
    return True


def kill_all_running() -> int:
    with _lock:
        entries = list(_running.values())
    for e in entries:
        e.cancelled.set()
        e.kill()
    return len(entries)
