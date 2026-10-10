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
from collections.abc import Iterable, Iterator

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

_SCRIPT_RE = re.compile(r"<\s*script\b", re.IGNORECASE)
# HTML parsers accept "/" as well as whitespace before an attribute.
_HANDLER_RE = re.compile(r"<[a-z][^>]*[\s/]on[a-z]+\s*=", re.IGNORECASE)
# A tag still open at the end of a line: the next line continues its attributes.
# Read as the HTML tokenizer does: the name runs to whitespace, "/" or ">"
# (``<b:x``), and nothing but ">" closes it, not a blank line or a fence.
_OPEN_TAG_RE = re.compile(r"<[a-z][^\s/>]*(?:[\s/][^>]*)?$", re.IGNORECASE)
# Raw HTML in markdown: "<" then a letter, "/", "!" or "?" (CommonMark tags,
# closing tags, comments, declarations, processing instructions).
_RAW_TAG_RE = re.compile(r"<[A-Za-z/!?]")
# CommonMark autolinks render as links, not HTML: <scheme:...> and <a@b.c>.
_AUTOLINK_RE = re.compile(
    r"<([A-Za-z][A-Za-z0-9+.-]{1,31}):[^\x00-\x20<>]*>"
    r"|<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>"
)
_SCRIPT_SCHEMES = frozenset({"javascript", "vbscript", "data"})
# A fence is trusted only at column 0: indented, it may belong to a list item
# that a later line closes, and the "code" after it would render as HTML.
# A backtick fence's info string may not hold a backtick (then it's prose).
_FENCE_OPEN_RE = re.compile(r"^(?:(`{3,})[^`]*|(~{3,}).*)$")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
# Where a CommonMark HTML block that starts on a line ends. Blocks 1-5 run to
# their end marker; anything else is taken to run to a blank line (types 6
# and 7, over-approximated: fences inside are raw text, not code).
_HTML_BLOCK_STARTS = (
    (re.compile(r"^ {0,3}<(?:pre|script|style|textarea)(?=[\s>]|$)", re.IGNORECASE),
     re.compile(r"</(?:pre|script|style|textarea)>", re.IGNORECASE)),
    (re.compile(r"^ {0,3}<!--"), re.compile(r"-->")),
    (re.compile(r"^ {0,3}<\?"), re.compile(r"\?>")),
    (re.compile(r"^ {0,3}<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"^ {0,3}<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"^ {0,3}</?[A-Za-z]"), None),  # ends at a blank line
)
# Only LF, CR and CRLF end a line (CommonMark); str.splitlines() also splits on
# form feed, NEL, U+2028 … which leaves a tag open in a browser.
_LINE_END_RE = re.compile(r"\r\n|\r|\n")
# Browsers strip leading C0 controls and spaces from a URL.
_BAD_SCHEME = (
    r"[\x00-\x20]*(?:(?:javascript|vbscript)[\x00-\x20]*:"
    r"|data[\x00-\x20]*:[\x00-\x20]*text/html)"
)
_JS_URL_RE = re.compile(
    rf"(?:href|src|action|formaction|xlink:href|data)\s*=\s*[\"']?{_BAD_SCHEME}"
    rf"|\]\(\s*<?{_BAD_SCHEME}"
    rf"|<{_BAD_SCHEME}"
    rf"|^\s*\[[^\]]+\]:\s*<?{_BAD_SCHEME}",  # markdown reference definition
    re.IGNORECASE,
)
# Markdown backslash escapes: ``javascript\:`` is ``javascript:`` in a link.
_MD_ESCAPE_RE = re.compile(r"\\(?=[!-/:-@\[-`{-~])")
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
        tag_open = _OPEN_TAG_RE.search(scan) is not None
        yield scan


def _outside_code(line: str) -> str:
    """``line`` with what can't be raw HTML blanked out, read left to right as
    CommonMark does: backslash escapes, code spans (a backtick run closed by
    one of the same length; unclosed, it's literal) and safe autolinks."""
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if c == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            close = re.compile(rf"(?<!`){'`' * (j - i)}(?!`)").search(line, j)
            if close is not None:
                out.append(" " * (close.end() - i))
                i = close.end()
            else:
                out.append(line[i:j])
                i = j
            continue
        if c == "<":
            m = _AUTOLINK_RE.match(line, i)
            if m is not None and (m.group(1) or "").lower() not in _SCRIPT_SCHEMES:
                out.append(" " * (m.end() - i))
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _html_block_end(line: str) -> re.Pattern[str] | None | bool:
    """The end marker of an HTML block this line starts; ``None`` for one that
    ends at a blank line; ``False`` when it starts none or ends on this line."""
    for start, end in _HTML_BLOCK_STARTS:
        m = start.match(line)
        if m is None:
            continue
        if end is not None and end.search(line, m.end()):
            return False
        return end
    return False


def _markdown_lines(lines: list[str]) -> Iterator[tuple[bool, str]]:
    """``(code, scan)`` per line of a markdown note: whether it is fenced code,
    and the line as the HTML rules see it (code spans, escapes and safe
    autolinks blanked; ``<x `` prefixed inside a tag left open). Fail closed:
    a fence counts only where CommonMark surely reads one — never while a tag
    or an HTML block is open."""
    fence: str | None = None
    tag_open = False
    block: re.Pattern[str] | None | bool = False  # see _html_block_end
    for line in lines:
        if fence is not None:
            m = _FENCE_CLOSE_RE.match(line)
            if m is not None and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            yield True, line
            continue
        if not tag_open and block is False:
            m = _FENCE_OPEN_RE.match(line)
            if m is not None:
                fence = m.group(1) or m.group(2)
                yield True, line
                continue
        text = _outside_code(line)
        scan = "<x " + text if tag_open else text
        tag_open = _OPEN_TAG_RE.search(scan) is not None
        if block is None:
            if line.strip(" \t") == "":
                block = False
        elif block is not False:
            if block.search(line):
                block = False
        else:
            block = _html_block_end(line)
        yield False, scan


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
    # Unknown or mixed suffix: judged as HTML. Raw HTML is the point of an
    # .html document, so only the tag rules apply there.
    markdown = bool(paths) and all(p.endswith(".md") for p in paths)
    new = _lines(change.after)
    added = _added_indices(change.before, change.after)
    added_set = set(added)
    # Tracked over the whole file: a kept line can open a tag or a fence.
    walk = _markdown_lines(new) if markdown else ((False, s) for s in _scan_lines(new))
    reasons: list[str] = []
    raw_html = False
    prose: list[str] = []  # the added lines outside fenced code
    for i, (code, scan) in enumerate(walk):
        if i not in added_set:
            continue
        line = new[i]
        fence = _FENCE_RE.match(line)
        if fence is not None:
            lang = fence.group(1).lower()
            if lang in _ALWAYS_EXECUTABLE or (in_template and lang in _EXECUTABLE_IN_TEMPLATES):
                _add(reasons, REASON_EXEC_FENCE)
        if code:
            continue
        prose.append(line)
        if _SCRIPT_RE.search(scan):
            _add(reasons, REASON_SCRIPT)
        if _HANDLER_RE.search(scan):
            _add(reasons, REASON_HANDLER)
        if _js_url(line) or _js_url(scan) or (markdown and _js_url(_MD_ESCAPE_RE.sub("", line))):
            _add(reasons, REASON_JS_URL)
        if markdown and _RAW_TAG_RE.search(scan):
            raw_html = True
    joined = "\n".join(prose)
    if REASON_JS_URL not in reasons and _js_url(joined):  # an attribute split across lines
        _add(reasons, REASON_JS_URL)
    if _TEMPLATE_EXPR_RE.search("\n".join(new[i] for i in added)):  # may span lines
        _add(reasons, REASON_TEMPLATE_EXPR)
    if raw_html and not {REASON_SCRIPT, REASON_HANDLER, REASON_JS_URL} & set(reasons):
        _add(reasons, REASON_RAW_HTML)  # the specific reason already says it
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
