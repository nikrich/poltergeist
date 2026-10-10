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
import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator

from ghostbrain.changes import log as _changes
from ghostbrain.vault_write import html_live
from ghostbrain.vault_write.html_live import HANDLER_RE, OPEN_TAG_RE, SCRIPT_RE, js_url
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
# A ``..`` segment, a Windows stream or 8.3 short name (``x:y``, ``PRO~1``), or
# a path that does not resolve to a writable file inside the vault: where it
# lands can't be judged by its name, so it waits.
REASON_PATH = "uses an unusual path (..)"
REASON_SCRIPT = "adds a <script> tag"
REASON_HANDLER = "adds an HTML event handler (on…=)"
REASON_JS_URL = "adds a script link (javascript:, vbscript:, data:text/html)"
# Markdown notes only (R15): any raw HTML outside code waits. The tag rules
# above stay for clearer messages; this is the safety net under them.
REASON_RAW_HTML = "adds raw HTML"
REASON_TEMPLATE_EXPR = "adds a template expression ({{ … }})"
REASON_EXEC_FENCE = "adds an executable code block"
REASON_DELETE = "deletes a note it didn't create"
REASON_MOVE = "moves a note it didn't create"

# Only LF, CR and CRLF end a line (CommonMark); str.splitlines() also splits on
# form feed, NEL, U+2028 … which leaves a tag open in a browser.
_LINE_END_RE = re.compile(r"\r\n|\r|\n")
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


# NTFS streams (``x.md::$DATA``, ``90-meta::$INDEX_ALLOCATION``) and 8.3 short
# names (``80-PRO~1``) can reach a protected file under another name.
_WINDOWS_ALIAS_RE = re.compile(r":|~\d")


def _windows_alias(path: str) -> bool:
    return any(_WINDOWS_ALIAS_RE.search(seg) for seg in _segments(path))


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
    flag says some path has ``..``, a Windows alias, or could not be placed in
    the vault."""
    return _judged(p for p in (change.rel_path, change.dest_path, *change.requested) if p)


def _judged(raw: Iterable[str]) -> tuple[list[str], bool]:
    out: list[str] = []
    odd = False
    for path in raw:
        if _traverses(path):
            odd = True
            continue
        if _windows_alias(path):
            odd = True
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


def protected_reasons(*paths: str) -> list[str]:
    """The name rules alone (90-meta, templates, stable profile) for these
    paths, judged as written and where they land. For writers no change row
    can hold (``UNLISTED_ACTORS``): the writer refuses these outright."""
    folded, _odd = _judged(p for p in paths if p)
    return _path_reasons(folded, False)


def _lines(data: bytes) -> list[str]:
    lines = _LINE_END_RE.split(data.decode("utf-8", errors="replace"))
    if lines[-1] == "":  # a final line ending starts no new line
        lines.pop()
    return lines


def _scan_lines(lines: list[str]) -> Iterator[str]:
    """Each line as the tag rules see it: prefixed with ``<x `` when it
    continues a tag left open on an earlier line."""
    tag_open = False
    for line in lines:
        scan = "<x " + line if tag_open else line
        tag_open = OPEN_TAG_RE.search(scan) is not None
        yield scan


def _diff(before: bytes | None, new: list[str]) -> tuple[list[int], dict[int, int]]:
    """The indices of the lines ``new`` adds or replaces, and for each line it
    keeps, its index in ``before``."""
    if before is None:
        return list(range(len(new))), {}
    matcher = difflib.SequenceMatcher(a=_lines(before), b=new, autojunk=False)
    added: list[int] = []
    kept: dict[int, int] = {}
    for tag, i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            added.extend(range(j1, j2))
        elif tag == "equal":
            kept.update(zip(range(j1, j2), range(i1, i1 + j2 - j1), strict=True))
    return added, kept


def added_lines(before: bytes | None, after: bytes | None) -> list[str]:
    """The lines ``after`` adds or replaces relative to ``before`` (spec B §3:
    only lines the change adds are checked)."""
    if after is None:
        return []
    new = _lines(after)
    return [new[j] for j in _diff(before, new)[0]]


_LIVE_REASONS = {
    html_live.SCRIPT: REASON_SCRIPT, html_live.HANDLER: REASON_HANDLER,
    html_live.JS_URL: REASON_JS_URL, html_live.RAW: REASON_RAW_HTML,
}


def _markdown_html_reasons(change: ProposedChange, new: list[str], added: list[int],
                           kept: dict[int, int]) -> list[str]:
    """R15-R17 (see ``html_live``): raw HTML an added line has outside code,
    and HTML the change makes live anywhere in the note."""
    before = None if change.before is None else _lines(change.before)
    found = html_live.markdown_findings(before, new, added, kept)
    reasons = [_LIVE_REASONS[k] for k in found]
    if REASON_RAW_HTML in reasons and len(reasons) > 1:
        reasons.remove(REASON_RAW_HTML)  # the specific reason already says it
    return reasons


def _html_doc_reasons(new: list[str], added: list[int]) -> list[str]:
    """The tag rules over the lines a change adds to a non-markdown file."""
    added_set = set(added)
    reasons: list[str] = []
    prose: list[str] = []
    for i, scan in enumerate(_scan_lines(new)):
        if i not in added_set:
            continue
        line = new[i]
        prose.append(line)
        if SCRIPT_RE.search(scan):
            _add(reasons, REASON_SCRIPT)
        if HANDLER_RE.search(scan):
            _add(reasons, REASON_HANDLER)
        if js_url(line) or js_url(scan):
            _add(reasons, REASON_JS_URL)
    if REASON_JS_URL not in reasons and js_url("\n".join(prose)):  # an attribute split across lines
        _add(reasons, REASON_JS_URL)
    return reasons


def _content_reasons(change: ProposedChange, paths: list[str]) -> list[str]:
    if change.after is None:
        return []
    in_template = any(p.startswith(_TEMPLATES_FOLDED) for p in paths)
    # Unknown or mixed suffix: judged as HTML. Raw HTML is the point of an
    # .html document, so only the tag rules apply there.
    markdown = bool(paths) and all(p.endswith(".md") for p in paths)
    new = _lines(change.after)
    added, kept = _diff(change.before, new)
    if markdown:
        reasons = _markdown_html_reasons(change, new, added, kept)
    else:
        reasons = _html_doc_reasons(new, added)
    for i in added:
        fence = _FENCE_RE.match(new[i])
        if fence is not None:
            lang = fence.group(1).lower()
            if lang in _ALWAYS_EXECUTABLE or (in_template and lang in _EXECUTABLE_IN_TEMPLATES):
                _add(reasons, REASON_EXEC_FENCE)
    if _TEMPLATE_EXPR_RE.search("\n".join(new[i] for i in added)):  # may span lines
        _add(reasons, REASON_TEMPLATE_EXPR)
    return _in_rule_order(reasons)


_CONTENT_ORDER = (
    REASON_SCRIPT, REASON_HANDLER, REASON_JS_URL, REASON_RAW_HTML, REASON_TEMPLATE_EXPR,
    REASON_EXEC_FENCE,
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
