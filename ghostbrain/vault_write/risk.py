"""Risk policy (spec B §3, slice B3): which non-user changes wait for approval.

The write path calls ``evaluate`` for every change the change log would
record (B2's ``records_change``: not ``user``, not ``restore``, not a worker
create). A non-empty list of reasons holds the change as ``pending``: nothing
is written until the user approves it on the Changes screen.

Plain prose edits and new notes are never held (user decision 2026-10-09:
apply now, revert in one click). Plugins may edit ``90-meta``, but always
through this hold (decision 3).
"""
from __future__ import annotations

import difflib
import html
import logging
import re
import unicodedata

from ghostbrain.changes import log as _changes
from ghostbrain.vault_write.writer import ProposedChange, _rel, resolve_safe

log = logging.getLogger("ghostbrain.vault_write.risk")

META_DIR = "90-meta/"
TEMPLATES_DIR = "90-meta/templates/"
STABLE_PROFILE_FILES = ("80-profile/working-style.md", "80-profile/preferences.md")
# Filing the user's jots is this job's whole purpose; it never creates them.
ROUTINE_MOVERS = frozenset({"worker:jot-router"})

REASON_META = "changes app settings (90-meta)"
REASON_TEMPLATE = "edits a template"
REASON_STABLE = "changes your stable profile"
# A ``..`` segment, or a path that does not resolve to a writable file inside
# the vault: where it lands can't be judged by its name, so it waits.
REASON_PATH = "uses an unusual path (..)"
REASON_SCRIPT = "adds a <script> tag"
REASON_HANDLER = "adds an HTML event handler (on…=)"
REASON_JS_URL = "adds a javascript: link"
REASON_TEMPLATE_EXPR = "adds a template expression ({{ … }})"
REASON_EXEC_FENCE = "adds an executable code block"
REASON_DELETE = "deletes a note it didn't create"
REASON_MOVE = "moves a note it didn't create"

_SCRIPT_RE = re.compile(r"<\s*script\b", re.IGNORECASE)
# HTML parsers accept "/" as well as whitespace before an attribute.
_HANDLER_RE = re.compile(r"<[a-z][^>]*[\s/]on[a-z]+\s*=", re.IGNORECASE)
# A tag still open at the end of a line: the next line continues its attributes.
# As in CommonMark raw HTML, the tag name ends at whitespace, "/" or the line
# end (``a<b:`` and ``i<n;`` are prose), and a blank line or code fence ends it.
_OPEN_TAG_RE = re.compile(r"<[a-z][a-z0-9-]*(?:[\s/][^>]*)?$", re.IGNORECASE)
_FENCE_LINE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})")
_JS_URL_RE = re.compile(
    r"(?:href|src|action|formaction|xlink:href|data)\s*=\s*[\"']?\s*javascript\s*:"
    r"|\]\(\s*<?\s*javascript\s*:"
    r"|<\s*javascript\s*:"
    r"|^\s*\[[^\]]+\]:\s*<?\s*javascript\s*:",  # markdown reference definition
    re.IGNORECASE,
)
# Browsers drop these inside a URL: java<TAB>script: is javascript:.
_URL_IGNORED_RE = re.compile(r"[\t\r\n]")
# Spec C placeholders: {{ name }}, {{ a.b }}, {{ a | filter: "arg" }}; quoted
# arguments may hold braces, and a placeholder may span lines.
_TEMPLATE_EXPR_RE = re.compile(
    r"\{\{\s*[A-Za-z_][\w.]*\s*"
    r"(?:\|(?:\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^{}\"'])*)?\}\}"
)
_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*([A-Za-z]+)")
_ALWAYS_EXECUTABLE = frozenset({"dataviewjs"})
_EXECUTABLE_IN_TEMPLATES = frozenset({"js", "javascript"})


def _fold(name: str) -> str:
    """NFKC + casefold: how case-insensitive filesystems (APFS, NTFS) compare
    names, so a ligature or fullwidth digit can't slip past a check. Same as
    ``ghostbrain.templates.render._fold``; not imported (that package imports
    this one)."""
    return unicodedata.normalize("NFKC", name).casefold()


def _segments(path: str) -> list[str]:
    return _fold(path).replace("\\", "/").split("/")


def _norm(path: str) -> str:
    """The path as the filesystem would match it: folded, ``/``-separated,
    no empty or ``.`` segments, and no trailing dots or spaces on a segment
    (Windows ignores them: ``90-meta./x.md`` is ``90-meta/x.md``)."""
    parts = (seg.rstrip(". ") for seg in _segments(path))
    return "/".join(seg for seg in parts if seg)


def _traverses(path: str) -> bool:
    """A ``..`` segment, however spelt (``..``, ``.. ``, fullwidth dots, ``\\``).
    ``_norm`` would drop it, so it is caught here and never resolved by name."""
    return any(seg.count(".") >= 2 and not seg.rstrip(". ") for seg in _segments(path))


def _canonical(path: str) -> str | None:
    """Where the write really lands, vault-relative (symlinks followed), or
    ``None`` when that can't be placed in the vault (fail closed)."""
    try:
        return _rel(resolve_safe(path))
    except Exception:  # noqa: BLE001 — InvalidPath, outside the vault, OSError
        return None


_META_FOLDED = _fold(META_DIR)
_TEMPLATES_FOLDED = _fold(TEMPLATES_DIR)
_STABLE_FOLDED = frozenset(_fold(p) for p in STABLE_PROFILE_FILES)


def _paths(change: ProposedChange) -> tuple[list[str], bool]:
    """Every spelling of the change's paths to judge, folded: as the caller
    asked for them and where they really land. A hold on either counts. The
    flag says some path has ``..`` or could not be placed in the vault."""
    raw = [p for p in (change.rel_path, change.dest_path, *change.requested) if p]
    out: list[str] = []
    odd = False
    for path in raw:
        if _traverses(path):
            odd = True
            continue
        out.append(_norm(path))
        canonical = _canonical(path)
        if canonical is None:
            odd = True
        else:
            out.append(_norm(canonical))
    return out, odd


def _add(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _path_reasons(paths: list[str], odd: bool) -> list[str]:
    reasons: list[str] = []
    for path in paths:
        if path.startswith(_TEMPLATES_FOLDED):
            _add(reasons, REASON_TEMPLATE)
        elif path.startswith(_META_FOLDED):
            _add(reasons, REASON_META)
        elif path in _STABLE_FOLDED:
            _add(reasons, REASON_STABLE)
    if odd and not reasons:  # already held by name: one reason is enough
        reasons.append(REASON_PATH)
    return reasons


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", errors="replace").splitlines()


def _added_indices(before: bytes | None, after: bytes) -> list[int]:
    new = _lines(after)
    if before is None:
        return list(range(len(new)))
    matcher = difflib.SequenceMatcher(a=_lines(before), b=new, autojunk=False)
    out: list[int] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            out.extend(range(j1, j2))
    return out


def added_lines(before: bytes | None, after: bytes | None) -> list[str]:
    """The lines ``after`` adds or replaces relative to ``before`` (spec B §3:
    only lines the change adds are checked)."""
    if after is None:
        return []
    new = _lines(after)
    return [new[j] for j in _added_indices(before, after)]


def _js_url(text: str) -> bool:
    """``javascript:`` as a browser reads it: entities decoded (``&#106;``,
    ``&colon;``), tab/CR/LF removed."""
    return _JS_URL_RE.search(_URL_IGNORED_RE.sub("", html.unescape(text))) is not None


def _content_reasons(change: ProposedChange, paths: list[str]) -> list[str]:
    if change.after is None:
        return []
    in_template = any(p.startswith(_TEMPLATES_FOLDED) for p in paths)
    new = _lines(change.after)
    added = _added_indices(change.before, change.after)
    added_set = set(added)
    reasons: list[str] = []
    tag_open = False  # tracked over the whole file: a kept line can open the tag
    for i, line in enumerate(new):
        # A line inside an unclosed tag is more of its attributes.
        boundary = not line.strip() or _FENCE_LINE_RE.match(line) is not None
        scan = "<x " + line if tag_open and not boundary else line
        tag_open = not boundary and _OPEN_TAG_RE.search(scan) is not None
        if i not in added_set:
            continue
        if _SCRIPT_RE.search(line):
            _add(reasons, REASON_SCRIPT)
        if _HANDLER_RE.search(scan):
            _add(reasons, REASON_HANDLER)
        if _js_url(line) or _js_url(scan):
            _add(reasons, REASON_JS_URL)
        fence = _FENCE_RE.match(line)
        if fence is not None:
            lang = fence.group(1).lower()
            if lang in _ALWAYS_EXECUTABLE or (in_template and lang in _EXECUTABLE_IN_TEMPLATES):
                _add(reasons, REASON_EXEC_FENCE)
    joined = "\n".join(new[i] for i in added)
    if REASON_JS_URL not in reasons and _js_url(joined):  # an attribute split across lines
        _add(reasons, REASON_JS_URL)
    if _TEMPLATE_EXPR_RE.search(joined):  # per-line matches included; may span lines
        _add(reasons, REASON_TEMPLATE_EXPR)
    return _in_rule_order(reasons)


_CONTENT_ORDER = (
    REASON_SCRIPT, REASON_HANDLER, REASON_JS_URL, REASON_TEMPLATE_EXPR, REASON_EXEC_FENCE,
)


def _in_rule_order(reasons: list[str]) -> list[str]:
    return [r for r in _CONTENT_ORDER if r in reasons]


def _ownership_reasons(change: ProposedChange) -> list[str]:
    if change.op not in ("delete", "move"):
        return []
    if change.op == "move" and change.actor in ROUTINE_MOVERS:
        return []
    try:
        mine = _changes.created_by(change.rel_path, change.actor)
    except Exception:  # noqa: BLE001 — unknown history: hold it (fail closed)
        log.warning("change log unavailable; holding %s of %s", change.op, change.rel_path)
        mine = False
    if mine:
        return []
    return [REASON_DELETE if change.op == "delete" else REASON_MOVE]


def evaluate(change: ProposedChange) -> list[str]:
    """Spec B §3. Reasons in rule order, each once. Empty: apply now."""
    paths, odd = _paths(change)
    reasons: list[str] = []
    found_by_rule = (
        _path_reasons(paths, odd), _content_reasons(change, paths), _ownership_reasons(change),
    )
    for found in found_by_rule:
        for reason in found:
            _add(reasons, reason)
    return reasons
