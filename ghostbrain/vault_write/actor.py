"""Who is writing. B1 validates and threads the actor; B2 records it on the
Changes screen. ``user`` writes never get a change row (spec B §1 step 7)."""
from __future__ import annotations

import re

Actor = str

USER: Actor = "user"
ASSISTANT: Actor = "assistant"
MCP: Actor = "mcp"

_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_ACTOR_RE = re.compile(rf"user|assistant|mcp|plugin:{_ID}|worker:{_ID}")


def parse_actor(value: str) -> Actor:
    if not isinstance(value, str) or not _ACTOR_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"invalid actor: {value!r}")
    return value


def plugin_actor(plugin_id: str) -> Actor:
    return parse_actor(f"plugin:{plugin_id}")


def worker_actor(job: str) -> Actor:
    return parse_actor(f"worker:{job}")
