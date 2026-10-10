"""Live ```query``` blocks (smart-templates spec, slice C2).

A query block is a closed grammar: one ``key: value`` per line, keys from
``functions.QUERY_KEYS``, ``#`` lines are comments. It is never YAML-loaded
and never evaluated, and user text reaches a regex only through re.escape.
Runs are bounded (rows, body reads, wall time); past a bound the run stops
and reports ``partial``. Templates may be AI-written (C4): treat every block
as untrusted input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

from ghostbrain.templates.functions import QUERY_KEYS
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic
from ghostbrain.vault_index.parse import normalize_target

MAX_QUERY_CHARS = 2_000
MAX_QUERY_LINES = 40
MAX_VALUE_CHARS = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_TEXT_READS = 2_000
MAX_NOTE_BYTES = 2_000_000
DEADLINE_S = 2.0
MIN_NAME_CHARS = 2
CLOSED_STATUSES = frozenset({"done", "closed"})
QUERY_KEY_NAMES: tuple[str, ...] = tuple(s.name for s in QUERY_KEYS)

_LINE_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)[ \t]*:[ \t]*(.*)")
_WIKILINK_VALUE_RE = re.compile(r"\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]")
_SINCE_REL_RE = re.compile(r"(\d{1,4})([dw])")
_SORT_RE = re.compile(r"(created|updated)(?:[ \t]+(asc|desc))?")
_STATUS_RE = re.compile(r"[a-z0-9_-]{1,32}")
_LIMIT_RE = re.compile(r"\d{1,9}")

SortField = Literal["created", "updated"]


@dataclass(frozen=True)
class Mention:
    target: str  # normalized vault key as written, e.g. "30-cross-context/people/alex.md" or "Alex.md"
    name: str    # body-text fallback: the alias, else the target's file stem


@dataclass(frozen=True)
class Query:
    type: str | None = None
    context: str | None = None
    tag: str | None = None
    mentions: Mention | None = None
    status: str | None = None
    since: date | None = None
    sort: SortField = "created"
    descending: bool = True
    limit: int = DEFAULT_LIMIT


def _diag(line: int, col: int, message: str, code: str, severity: str = "error") -> Diagnostic:
    return Diagnostic(line=line, col=col, severity=severity, message=message, code=code)  # type: ignore[arg-type]


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].strip()
    return v


def _has_placeholder(value: str) -> bool:
    """Same `{{ … }}` grammar as C1: a hand-typed block can't be filled in."""
    if "{{" not in value:
        return False
    try:
        return any(isinstance(seg, Placeholder) for seg in tokenize(value))
    except TemplateLimitError:
        return True


def _parse_mention(value: str) -> Mention | None:
    m = _WIKILINK_VALUE_RE.fullmatch(value)
    if m is None and ("[" in value or "]" in value):
        return None
    raw, alias = (m.group(1), m.group(2) or "") if m else (value.lstrip("@"), "")
    target = normalize_target(raw)
    if target is None:
        return None
    name = alias.strip().lstrip("@").strip() or PurePosixPath(target).stem
    return Mention(target=target, name=name)


def _parse_since(value: str, today: date) -> date | None:
    m = _SINCE_REL_RE.fullmatch(value)
    if m:
        days = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return today - timedelta(days=days)
    if len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _apply(
    key: str, value: str, line: int, col: int, today: date,
    fields: dict[str, Any], diags: list[Diagnostic],
) -> None:
    low = value.lower()
    if key in ("type", "context"):
        fields[key] = low
    elif key == "tag":
        tag = low.lstrip("#").strip()
        if not tag:
            diags.append(_diag(line, col, "`tag` needs a tag name", "bad-value"))
            return
        fields["tag"] = tag
    elif key == "mentions":
        mention = _parse_mention(value)
        if mention is None:
            diags.append(_diag(line, col, "`mentions` takes a note link like "
                               "[[30-cross-context/people/alex]] or a name", "bad-value"))
            return
        fields["mentions"] = mention
    elif key == "status":
        if not _STATUS_RE.fullmatch(low):
            diags.append(_diag(line, col, "`status` takes one word, such as open or done", "bad-value"))
            return
        fields["status"] = low
    elif key == "since":
        since = _parse_since(low, today)
        if since is None:
            diags.append(_diag(line, col, "`since` takes 7d, 2w or a date like 2026-10-01", "bad-value"))
            return
        fields["since"] = since
    elif key == "sort":
        m = _SORT_RE.fullmatch(low)
        if m is None:
            diags.append(_diag(line, col, "`sort` takes created or updated, then asc or desc", "bad-value"))
            return
        fields["sort"] = m.group(1)
        fields["descending"] = m.group(2) != "asc"
    elif key == "limit":
        if not _LIMIT_RE.fullmatch(low) or int(low) < 1:
            diags.append(_diag(line, col, f"`limit` takes a whole number from 1 to {MAX_LIMIT}", "bad-value"))
            return
        n = int(low)
        if n > MAX_LIMIT:
            diags.append(_diag(line, col, f"limit capped at {MAX_LIMIT}", "limit-capped", "warning"))
            n = MAX_LIMIT
        fields["limit"] = n


def parse_query_block(text: str, *, today: date | None = None) -> tuple[Query | None, list[Diagnostic]]:
    """Parse the text inside a ```query``` fence. Any error → (None, diagnostics)."""
    if len(text) > MAX_QUERY_CHARS:
        return None, [_diag(1, 1, f"query is too long (max {MAX_QUERY_CHARS} characters)", "query-too-long")]
    lines = text.split("\n")
    if len(lines) > MAX_QUERY_LINES:
        return None, [_diag(MAX_QUERY_LINES + 1, 1, f"query has too many lines (max {MAX_QUERY_LINES})",
                            "query-too-long")]
    today = today or date.today()
    diags: list[Diagnostic] = []
    seen: set[str] = set()
    fields: dict[str, Any] = {}
    for n, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        m = _LINE_RE.fullmatch(line)
        if m is None:
            diags.append(_diag(n, indent + 1, "expected `key: value`", "syntax"))
            continue
        key = m.group(1).lower()
        col = indent + m.start(2) + 1
        if key not in QUERY_KEY_NAMES:
            diags.append(_diag(n, indent + 1, f"unknown key `{key}`; use one of: {', '.join(QUERY_KEY_NAMES)}",
                               "unknown-key"))
            continue
        if key in seen:
            diags.append(_diag(n, indent + 1, f"`{key}` is set twice", "duplicate-key"))
            continue
        seen.add(key)
        value = _unquote(m.group(2))
        if not value:
            diags.append(_diag(n, col, f"`{key}` needs a value", "empty-value"))
            continue
        if len(value) > MAX_VALUE_CHARS:
            diags.append(_diag(n, col, f"`{key}` value is too long (max {MAX_VALUE_CHARS} characters)",
                               "value-too-long"))
            continue
        if _has_placeholder(value):
            diags.append(_diag(n, col, "placeholders such as {{person.link}} are filled in only when a note "
                                       "is made from a template", "unresolved-placeholder"))
            continue
        _apply(key, value, n, col, today, fields, diags)
    if not seen and not diags:
        diags.append(_diag(1, 1, "empty query; add a filter such as `type: action_item`", "empty-query"))
    if any(d.severity == "error" for d in diags):
        return None, diags
    return Query(**fields), diags
