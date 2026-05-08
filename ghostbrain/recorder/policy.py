"""Should-we-record decision. Pure function — no I/O, no side effects."""

from __future__ import annotations

import dataclasses
import re
from typing import Iterable


@dataclasses.dataclass
class RecorderPolicy:
    """Tunables loaded from config.yaml's ``recorder`` block."""

    enabled: bool = True
    # Title patterns that disable recording. Matches the WHOLE title,
    # case-insensitive, with simple wildcard ``*`` support.
    excluded_titles: tuple[str, ...] = ("Focus", "focus")
    # Contexts to skip recording for entirely.
    excluded_contexts: tuple[str, ...] = ()
    # Contexts to record (empty = record all not in excluded_contexts).
    included_contexts: tuple[str, ...] = ()


def should_record(
    *,
    title: str,
    context: str,
    policy: RecorderPolicy,
) -> tuple[bool, str]:
    """Return (decision, reason). Reason explains either acceptance or skip."""
    if not policy.enabled:
        return False, "recorder disabled in config"

    if _matches_any(title, policy.excluded_titles):
        return False, f"title matches exclusion: {title!r}"

    if context in policy.excluded_contexts:
        return False, f"context excluded: {context}"

    if policy.included_contexts and context not in policy.included_contexts:
        return False, f"context not in included list: {context}"

    return True, "passed all filters"


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    """Case-insensitive whole-string match with ``*`` wildcards."""
    for pat in patterns:
        regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
        if re.match(regex, value, flags=re.IGNORECASE):
            return True
    return False
