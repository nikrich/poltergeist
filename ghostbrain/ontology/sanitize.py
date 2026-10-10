"""Shared sanitisers for user/note data embedded in LLM prompts.

Prompt templates delimit data with literal ``<<<`` / ``>>>`` lines and ``### NOTE``-style
headers. Anything untrusted must not be able to produce those sequences, so every
run of three or more ``>`` or ``<`` is broken up, and line-leading ``###`` is defused.
"""
from __future__ import annotations

import re

_ANGLE_RUN = re.compile(r">{3,}|<{3,}")
_HEADER = re.compile(r"(?m)^(\s*)#{3}")
_WS = re.compile(r"\s+")


def neutralise(text: str) -> str:
    """Multi-line-safe: no ``>>>`` / ``<<<`` survives, and no line starts with ``###``."""
    spaced = _ANGLE_RUN.sub(lambda m: " ".join(m.group()), text)
    return _HEADER.sub(lambda m: f"{m.group(1)}# # #", spaced)


def one_line(text: str, limit: int | None = None) -> str:
    """Neutralise, then collapse all whitespace (including newlines) to single spaces."""
    flat = _WS.sub(" ", neutralise(str(text))).strip()
    return flat[:limit].rstrip() if limit is not None else flat
