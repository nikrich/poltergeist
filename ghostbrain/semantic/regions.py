"""Single source of truth for context → region colour + label."""
from __future__ import annotations

import hashlib

_BASE = {
    "poltergeist": "#6EE7A8",
    "sanlam": "#38BDF8",
    "personal": "#A78BFA",
    "reducedrecipes": "#FBBF24",
    "codeship": "#F472B6",
}

# Extended ramp for unknown contexts: even lightness, varied hue.
_RAMP = ["#5EEAD4", "#818CF8", "#F0ABFC", "#FB7185", "#FCD34D",
         "#4ADE80", "#22D3EE", "#C084FC", "#F87171", "#A3E635"]


def region_color(context: str) -> str:
    if context in _BASE:
        return _BASE[context]
    h = int(hashlib.sha1(context.encode("utf-8")).hexdigest(), 16)
    return _RAMP[h % len(_RAMP)]


def region_label(context: str) -> str:
    return context or "unfiled"
