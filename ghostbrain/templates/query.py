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
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from ghostbrain.templates.functions import QUERY_KEYS
from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic
from ghostbrain.vault_index.links import LinkIndex, link_key
from ghostbrain.vault_index.parse import SNIPPET_MAX, NoteEntry, normalize_target, split_frontmatter
from ghostbrain.vault_write.etag import compute_etag

MAX_QUERY_CHARS = 2_000
MAX_QUERY_LINES = 40
MAX_VALUE_CHARS = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_TEXT_READS = 2_000
MAX_NOTE_BYTES = 2_000_000
DEADLINE_S = 2.0
MIN_NAME_CHARS = 2
MAX_HEADING_LINE_CHARS = 500
CLOSED_STATUSES = frozenset({"done", "closed"})
QUERY_KEY_NAMES: tuple[str, ...] = tuple(s.name for s in QUERY_KEYS)

_LINE_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)[ \t]*:[ \t]*(.*)")
_WIKILINK_VALUE_RE = re.compile(r"\[\[([^\[\]|#\n]+)(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]")
_SINCE_REL_RE = re.compile(r"(\d{1,4})([dw])")
_SORT_RE = re.compile(r"(created|updated)(?:[ \t]+(asc|desc))?")
_STATUS_RE = re.compile(r"[a-z0-9_-]{1,32}")
_LIMIT_RE = re.compile(r"\d{1,9}")
_H1_RE = re.compile(r"#[ \t]+(.+)")

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


@dataclass(frozen=True)
class QueryRow:
    path: str
    title: str
    context: str
    status: str | None
    created: str | None
    snippet: str
    etag: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path, "title": self.title, "context": self.context, "status": self.status,
            "created": self.created, "snippet": self.snippet, "etag": self.etag,
        }


@dataclass(frozen=True)
class QueryRun:
    rows: tuple[QueryRow, ...]
    partial: bool


@dataclass(frozen=True)
class _Target:
    page: str | None                  # the mentioned note's own path, if it exists
    key: str                          # link_key of the resolved target
    pattern: re.Pattern[str] | None   # whole-word names for the body-text fallback


def _opt(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _timestamp(value: str | None, mtime_ns: int) -> float:
    if value:
        try:
            parsed = datetime.fromisoformat(value.strip())  # 3.11+: accepts Z
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return mtime_ns / 1_000_000_000


def _day(value: str | None, mtime_ns: int) -> date:
    try:
        return datetime.fromtimestamp(_timestamp(value, mtime_ns), tz=UTC).date()
    except (ValueError, OverflowError, OSError):
        return date.min


def _matches_fields(q: Query, e: NoteEntry) -> bool:
    if q.type is not None and q.type not in {(e.artifact_type or "").lower(), (e.type or "").lower()}:
        return False
    if q.context is not None and e.context.lower() != q.context:
        return False
    if q.tag is not None and q.tag not in {t.lower().lstrip("#") for t in (*e.tags, *e.hashtags)}:
        return False
    if q.status is not None:
        status = (e.status or "").lower()
        if q.status == "open":
            if status in CLOSED_STATUSES:
                return False
        elif status != q.status:
            return False
    return q.since is None or _day(e.created, e.mtime_ns) >= q.since


def _sort_key(e: NoteEntry, q: Query) -> tuple[float, str]:
    ts = _timestamp(e.created if q.sort == "created" else e.updated, e.mtime_ns)
    return (-ts if q.descending else ts, e.path)


def _resolve_mention(mention: Mention, index: LinkIndex) -> _Target:
    resolved = index.resolve(mention.target)
    page = index.get(resolved)
    names = {mention.name.strip()}
    if page is not None:
        names.add(page.title.strip())
    usable = sorted((n for n in names if len(n) >= MIN_NAME_CHARS), key=len, reverse=True)
    pattern = (
        re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in usable) + r")(?!\w)", re.IGNORECASE)
        if usable else None
    )
    return _Target(page=resolved if page is not None else None, key=link_key(resolved), pattern=pattern)


def _links_to(e: NoteEntry, target: _Target, index: LinkIndex) -> bool:
    return any(link_key(index.resolve(link.target)) == target.key for link in e.links)


def _read_bytes(root: Path, rel: str) -> bytes | None:
    """Bytes of an indexed note; None if gone, unreadable or over MAX_NOTE_BYTES."""
    try:
        path = root / rel
        if path.stat().st_size > MAX_NOTE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _body_text(root: Path, rel: str) -> str | None:
    data = _read_bytes(root, rel)
    if data is None:
        return None
    _, body = split_frontmatter(data.decode("utf-8", errors="replace"))
    return _strip_query_fences(body)


def _strip_query_fences(body: str) -> str:
    """Drop each ```query fence, opening line through closing ``` line, in one
    linear pass. An unclosed fence runs to the end of the note, as in
    CommonMark, so a half-typed block never counts as body text."""
    out: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if in_fence:
            if line.startswith("```") and not line[3:].strip(" \t\r"):
                in_fence = False
            continue
        if line.startswith("```query"):
            in_fence = True
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def _first_heading(body: str) -> str | None:
    for line in body.splitlines()[:50]:
        line = line.strip()
        if len(line) > MAX_HEADING_LINE_CHARS:
            continue
        m = _H1_RE.fullmatch(line)
        if m:
            title = m.group(1).rstrip(" \t#").strip()
            if title:
                return title
    return None


def _first_line(body: str) -> str:
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith("#"):
            continue
        return s[:SNIPPET_MAX]
    return ""


def _row(root: Path, e: NoteEntry) -> QueryRow | None:
    if not (root / e.path).is_file():
        return None  # deleted since it was indexed
    data = _read_bytes(root, e.path)
    if data is None:  # too large (or vanished mid-read): index data only, no etag
        return QueryRow(e.path, e.title, e.context, e.status, e.created, "", None)
    meta, body = split_frontmatter(data.decode("utf-8", errors="replace"))
    title = _opt(meta.get("title")) or _first_heading(body) or e.title
    return QueryRow(
        path=e.path, title=title, context=e.context, status=_opt(meta.get("status")),
        created=e.created, snippet=_first_line(body), etag=compute_etag(data),
    )


def run_query(
    query: Query,
    index: LinkIndex,
    *,
    clock: Callable[[], float] = time.monotonic,
    deadline_s: float = DEADLINE_S,
    max_text_reads: int = MAX_TEXT_READS,
) -> QueryRun:
    """Filter → sort → (mentions) → first ``query.limit`` rows. Bounded:
    body reads for the name fallback stop at ``max_text_reads`` or
    ``deadline_s`` and the run reports ``partial``."""
    started = clock()
    candidates = [e for e in index.entries() if _matches_fields(query, e)]
    candidates.sort(key=lambda e: _sort_key(e, query))
    target = _resolve_mention(query.mentions, index) if query.mentions is not None else None
    picked: list[NoteEntry] = []
    reads = 0
    partial = False
    for entry in candidates:
        if len(picked) >= query.limit:
            break
        if target is not None:
            if entry.path == target.page:
                continue
            if not _links_to(entry, target, index):
                if target.pattern is None:
                    continue
                if reads >= max_text_reads or clock() - started > deadline_s:
                    partial = True
                    break
                reads += 1
                body = _body_text(index.root, entry.path)
                if body is None or not target.pattern.search(body):
                    continue
        picked.append(entry)
    rows = tuple(row for row in (_row(index.root, e) for e in picked) if row is not None)
    return QueryRun(rows=rows, partial=partial)
