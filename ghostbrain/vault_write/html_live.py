"""Live HTML in a note's text (spec B §3; task 10: rulings R15-R17).

The tag and script-link patterns the risk rules share, and how a markdown
note is read to find which of its HTML is live.

A non-user change to a markdown note waits for approval when a line it adds
has raw-HTML syntax outside code (R15), or when the AFTER text has live HTML
(a tag, an event handler, a script link) the BEFORE text did not (R17). The
two texts are read differently, and each reading errs towards a hold:

* the after text strictly: text is code only where every CommonMark reading
  agrees it is code. A fence at column 0 with its closer, or a code span whose
  pairing nothing earlier in the paragraph can change. HTML-block lines are
  read raw (R16).
* the before text leniently: whatever some reading hides is inert there (code,
  a link's destination or title, image alt text, a reference definition, a
  tag a table row would split, and in the browser a comment, raw text or an
  attribute value), so it can't excuse live HTML in the after text.

HTML that was live before stays unheld on an unrelated edit, since it is live
in both readings. A change that makes kept, inert HTML live is held like an
added line.
"""
from __future__ import annotations

import html
import re
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

# What a change can add, in rule order.
SCRIPT, HANDLER, JS_URL, RAW = "script", "handler", "js_url", "raw"

SCRIPT_RE = re.compile(r"<\s*script\b", re.IGNORECASE)
# HTML parsers accept "/" as well as whitespace before an attribute.
HANDLER_RE = re.compile(r"<[a-z][^>]*[\s/]on[a-z]+\s*=", re.IGNORECASE)
# A tag still open at the end of a line: the next line continues its attributes.
# Read as the HTML tokenizer does: the name runs to whitespace, "/" or ">"
# (``<b:x``), and nothing but ">" closes it, not a blank line or a fence.
OPEN_TAG_RE = re.compile(r"<[a-z][^\s/>]*(?:[\s/][^>]*)?$", re.IGNORECASE)
# Raw HTML in markdown: "<" then a letter, "/", "!" or "?" (CommonMark tags,
# closing tags, comments, declarations, processing instructions).
RAW_TAG_RE = re.compile(r"<[A-Za-z/!?]")
# CommonMark autolinks render as links, not HTML: <scheme:...> and <a@b.c>.
_AUTOLINK_RE = re.compile(
    r"<([A-Za-z][A-Za-z0-9+.-]{1,31}):[^\x00-\x20<>]*>"
    r"|<[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>"
)
_SCRIPT_SCHEMES = frozenset({"javascript", "vbscript", "data"})

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
MD_ESCAPE_RE = re.compile(r"\\(?=[!-/:-@\[-`{-~])")
# Browsers drop these inside a URL: java<TAB>script: is javascript:.
_URL_IGNORED_RE = re.compile(r"[\t\r\n]")


_TAG_LETTER_RE = re.compile(r"<[a-z]", re.IGNORECASE)
_ON_ATTR_RE = re.compile(r"[\s/]on[a-z]+\s*=", re.IGNORECASE)


def handlers(text: str) -> int:
    """``len(HANDLER_RE.findall(text))`` in linear time: a match can't cross
    a ">", and the greedy match takes a whole stretch between two of them."""
    count = 0
    for stretch in text.split(">"):
        tag = _TAG_LETTER_RE.search(stretch)
        if tag is not None and _ON_ATTR_RE.search(stretch, tag.end()):
            count += 1
    return count


def tag_left_open(text: str) -> bool:
    """``OPEN_TAG_RE.search(text)`` in linear time: a tag starts after the last ">"."""
    return _TAG_LETTER_RE.search(text, text.rfind(">") + 1) is not None


def js_url(text: str) -> bool:
    """``javascript:`` as a browser reads it: entities decoded (``&#106;``,
    ``&colon;``), tab/CR/LF removed."""
    return _JS_URL_RE.search(_URL_IGNORED_RE.sub("", html.unescape(text))) is not None


# ── markdown block structure ──────────────────────────────────────────────

# Container markers (blockquote ">", list "-" "+" "*" "1." "1)") and the
# indentation in front of a line's content.
_PREFIX = r"(?:[ \t]*(?:>|(?:[-+*]|\d{1,9}[.)])(?=[ \t])))*[ \t]*"
_PREFIX_RE = re.compile(_PREFIX)
# A line some container could read as a fence opener. A backtick fence's info
# string may not hold a backtick (then it's prose).
_FENCE_SHAPE_RE = re.compile(rf"({_PREFIX})(?:(`{{3,}})[^`]*|(~{{3,}}).*)$")
_FENCE_CLOSE_RE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*$")
_NESTED_CLOSE_RE = re.compile(r"( *)(`{3,}|~{3,})[ \t]*$")
_LIST_MARKER_RE = re.compile(r"[-+*]|\d{1,9}[.)]")
# A GFM table delimiter row. markdown-it tries tables before fences and HTML
# blocks: a line above one may be a table header instead.
_DELIMITER_ROW_RE = re.compile(r"[ \t]*[|:\-][|:\- \t]*$")


def _header_row(lines: list[str], i: int) -> bool:
    """Line ``i`` may be a table's header row: it holds a "|" and the next
    line, inside its containers, is a delimiter row."""
    if i + 1 >= len(lines) or "|" not in lines[i]:
        return False
    nxt = lines[i + 1][_PREFIX_RE.match(lines[i + 1]).end():]
    return "-" in nxt and _DELIMITER_ROW_RE.match(nxt) is not None

# CommonMark HTML blocks 1-5: (start, end, start that every renderer reads as
# a block). markdown-it only takes an upper-case declaration for type 4.
_BLOCKS_1_TO_5 = (
    (re.compile(r"<(?:script|pre|style|textarea)(?=[\s>]|$)", re.IGNORECASE),
     re.compile(r"</(?:script|pre|style|textarea)>", re.IGNORECASE), None),
    (re.compile(r"<!--"), re.compile(r"-->"), None),
    (re.compile(r"<\?"), re.compile(r"\?>"), None),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>"), None),
    (re.compile(r"<![A-Za-z]"), re.compile(r">"), re.compile(r"<![A-Z]")),
)
# Type 6 (ends at a blank line). "search" and "source" are each named by only
# one CommonMark version, so they start a block for sure only when type 7
# would too.
_TYPE6_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)(?=\s|/?>|$)")
_TYPE6_NAMES = frozenset({
    "address", "article", "aside", "base", "basefont", "blockquote", "body", "caption",
    "center", "col", "colgroup", "dd", "details", "dialog", "dir", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2",
    "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "iframe", "legend", "li", "link",
    "main", "menu", "menuitem", "nav", "noframes", "ol", "optgroup", "option", "p", "param",
    "search", "section", "source", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
    "title", "tr", "track", "ul",
})
_TYPE6_SURE = _TYPE6_NAMES - {"search", "source"}
# CommonMark's inline raw HTML (markdown-it's html_re): anything else after a
# "<" in a paragraph is escaped text. A line holding only an open or closing
# tag starts a type-7 block, but not inside a paragraph.
_ATTRIBUTE = (
    r"(?:\s+[A-Za-z_:][A-Za-z0-9:._-]*"
    r"""(?:\s*=\s*(?:[^"'=<>`\x00-\x20]+|'[^']*'|"[^"]*"))?)"""
)
_OPEN_CLOSE = rf"<[A-Za-z][A-Za-z0-9-]*{_ATTRIBUTE}*\s*/?>|</[A-Za-z][A-Za-z0-9-]*\s*>"
_INLINE_HTML_RE = re.compile(
    rf"{_OPEN_CLOSE}|<!---?>|<!--(?:[^-]|-[^-]|--[^>])*-->|<\?[\s\S]*?\?>"
    r"|<![A-Za-z][^>]*>|<!\[CDATA\[[\s\S]*?\]\]>"
)
_TYPE7_RE = re.compile(rf"(?:{_OPEN_CLOSE})\s*$")
_INLINE_START_RE = re.compile(r"<(?:/?[A-Za-z]|!|\?)")
# How far inline HTML is followed; past this its extent is unknown, which
# each reading resolves towards a hold. Keeps a note with thousands of
# unclosed "<!--" from costing quadratic time.
_WINDOW = 4096
_UNKNOWN = -1


# What ends a comment, processing instruction, CDATA section or declaration.
_TERMINATORS = (("<!--", "-->", 2), ("<?", "?>", 2), ("<![CDATA[", "]]>", 9), ("<!", ">", 2))


@lru_cache(maxsize=65536)  # cleared after each note (markdown_findings)
def _inline_html_end(text: str, pos: int) -> int | None:
    """Where the inline HTML starting at ``pos`` ends; ``_UNKNOWN`` when it
    may run past the window; None when none starts there."""
    for start, end, skip in _TERMINATORS:
        if text.startswith(start, pos):
            if text.find(end, pos + skip, pos + _WINDOW) < 0:
                break  # it can't end in the window: skip the regex
            m = _INLINE_HTML_RE.match(text, pos, pos + _WINDOW)
            if m is not None:
                return m.end()
            break
    else:
        m = _INLINE_HTML_RE.match(text, pos, pos + _WINDOW)
        if m is not None:
            return m.end()
    if pos + _WINDOW < len(text) and _INLINE_START_RE.match(text, pos):
        return _UNKNOWN
    return None

# Front matter as the app (python-frontmatter) and Obsidian read it.
_FM_OPEN_RE = re.compile(r"[ \t]*-{3,}[ \t]*$")
_FM_CLOSE_RES = (_FM_OPEN_RE, re.compile(r"---$"), re.compile(r"\.\.\.[ \t]*$"))
# Obsidian comment and math blocks: renderers disagree about what is inside.
_REGION_MARKS = ("%%", "$$")

_TEXT, _FENCE, _NESTED, _UNCLOSED, _AMBIGUOUS = "text", "fence", "nested", "unclosed", "ambiguous"


@dataclass
class _Walk:
    """How each line sits in the note's blocks.

    ``kind``: ``fence`` (a trusted fence: certainly code); ``nested`` (a fence
    inside a container or indented, cleanly closed so far); ``unclosed`` and
    ``ambiguous`` (from here on the fence structure is not known: an opener
    with no closer, or a fence-like line no reading can place); ``text``.
    ``block``: in an HTML block (True: in every reading; False: in some).
    ``region``: ``fm`` (front matter), ``%%`` or ``$$``.
    """

    kind: list[str]
    block: list[bool | None]
    region: list[str | None]


def _blank_line(line: str) -> bool:
    return line.strip(" \t") == ""


def _closes(line: str, char: str, size: int) -> bool:
    m = _FENCE_CLOSE_RE.match(line)
    return m is not None and m.group(1)[0] == char and len(m.group(1)) >= size


def _nested_step(line: str, char: str, size: int, prefix: str) -> str:
    """``in``, ``close`` or ``break`` for a line inside a fence opened behind
    ``prefix`` (container markers as spaces, except ``>``). It stays certain
    only while each line keeps the prefix and its closer sits right after it;
    anything else may have ended the container, and the fence with it."""
    if not line.startswith(prefix):
        if prefix.strip() == "" and _blank_line(line):
            return "in"  # a blank line inside a list item
        if prefix.rstrip() and line.rstrip() == prefix.rstrip():
            return "in"  # an empty quote line
        return "break"
    m = _NESTED_CLOSE_RE.match(line, len(prefix))
    if m is None or m.group(2)[0] != char or len(m.group(2)) < size or len(m.group(1)) > 3:
        return "in"
    return "close" if m.group(1) == "" else "break"


def _front_matter_end(lines: list[str]) -> int:
    """The last line any reader takes for front matter; -1 for none."""
    first = next((i for i, line in enumerate(lines) if not _blank_line(line)), None)
    if first is None or not _FM_OPEN_RE.match(lines[first]):
        return -1
    ends = (next((j for j in range(first + 1, len(lines)) if close.match(lines[j])), -1)
            for close in _FM_CLOSE_RES)
    return max(ends)


def _toggle_regions(open_marks: dict[str, bool], line: str) -> str | None:
    """The Obsidian region the line is in, updating which are open after it."""
    was = next((m for m in _REGION_MARKS if open_marks[m]), None)
    for mark in _REGION_MARKS:
        if line.count(mark) % 2:
            open_marks[mark] = not open_marks[mark]
    return was or next((m for m in _REGION_MARKS if open_marks[m]), None)


def _html_start(line: str, may_be_sure: bool, after_blank: bool,
                ) -> tuple[re.Pattern[str] | None, bool, bool] | None:
    """``(end, sure, stays_open)`` when the line may start an HTML block. Any
    container prefix is allowed, so this covers every reading; ``sure`` only
    at column 0 or 1 outside containers, where every reading agrees. ``end``
    None: the block ends at a blank line."""
    plen = _PREFIX_RE.match(line).end()
    content = line[plen:]
    if not content.startswith("<"):
        return None
    sure = may_be_sure and line[:plen] in ("", " ")
    for start, end, sure_start in _BLOCKS_1_TO_5:
        if start.match(content):
            sure = sure and (sure_start is None or sure_start.match(content) is not None)
            return end, sure, end.search(content) is None
    complete = after_blank and _TYPE7_RE.match(content) is not None
    m = _TYPE6_RE.match(content)
    if m is not None and m.group(1).lower() in _TYPE6_NAMES:
        return None, sure and (m.group(1).lower() in _TYPE6_SURE or complete), True
    if _TYPE7_RE.match(content):
        return None, sure and complete, True
    return None


def _walk(lines: list[str]) -> _Walk:
    """Read the block structure, trusting fences only while it is certain."""
    n = len(lines)
    walk = _Walk([_TEXT] * n, [None] * n, [None] * n)
    fm_end = _front_matter_end(lines)
    fence: tuple[str, int, str | None] | None = None  # char, size, prefix (None: column 0)
    lost: str | None = None  # _UNCLOSED / _AMBIGUOUS from here on
    block: tuple[re.Pattern[str] | None, bool] | None = None  # end, sure
    open_marks = dict.fromkeys(_REGION_MARKS, False)
    after_blank = True
    for i, line in enumerate(lines):
        blank = _blank_line(line)
        if fence is not None:
            char, size, prefix = fence
            if prefix is None:
                walk.kind[i] = _FENCE
                if _closes(line, char, size):
                    fence = None
                after_blank = False
                continue
            step = _nested_step(line, char, size, prefix)
            if step != "break":
                walk.kind[i] = _NESTED
                walk.region[i] = _toggle_regions(open_marks, line)
                if step == "close":
                    fence = None
                after_blank = blank
                continue
            fence, lost = None, _AMBIGUOUS
        region = "fm" if i <= fm_end else _toggle_regions(open_marks, line)
        walk.region[i] = region
        if lost is not None:
            walk.kind[i] = lost
        shape = _FENCE_SHAPE_RE.match(line)
        if block is not None:
            end, sure = block
            walk.block[i] = sure
            if shape is not None and not sure and lost is None:
                lost = walk.kind[i] = _AMBIGUOUS  # raw text in one reading, a fence in another
            if end is None and blank:
                walk.block[i] = block = None
            elif end is not None and end.search(line):
                # A container may have ended the block first; then markdown-it
                # reads this line as a type-7 block running to a blank line (I-B).
                block = None if sure else (None, False)
        elif shape is not None and lost is None:
            prefix, run = shape.group(1), shape.group(2) or shape.group(3)
            if region is not None or "\t" in prefix or _header_row(lines, i):
                lost = walk.kind[i] = _AMBIGUOUS
            elif prefix:
                walk.kind[i] = _NESTED
                fence = (run[0], len(run),
                         _LIST_MARKER_RE.sub(lambda m: " " * len(m.group()), prefix))
            elif any(_closes(later, run[0], len(run)) for later in lines[i + 1:]):
                walk.kind[i] = _FENCE
                fence = (run[0], len(run), None)
            else:
                lost = walk.kind[i] = _UNCLOSED
        else:
            start = _html_start(line, lost is None and region is None and not _header_row(lines, i),
                                after_blank)
            if start is not None:
                end, sure, stays_open = start
                if region is not None and lost is None:
                    lost = walk.kind[i] = _AMBIGUOUS
                walk.block[i] = sure
                if stays_open:
                    block = (end, sure)
        after_blank = blank
    return walk


# ── code spans ────────────────────────────────────────────────────────────

_RUN_RE = re.compile(r"`+")
# A "|" a GFM table row splits cells at (an even run of backslashes before it).
_TABLE_PIPE_RE = re.compile(r"(?<!\\)(?:\\\\)*\|")
Ranges = list[tuple[int, int]]


def _segments(lines: list[str], walk: _Walk) -> Iterator[list[int]]:
    """Runs of non-blank lines outside trusted fences: every paragraph lies
    inside one, so a code span can't pair across two."""
    seg: list[int] = []
    for i, line in enumerate(lines):
        if walk.kind[i] == _FENCE or _blank_line(line):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(i)
    if seg:
        yield seg


def _later_runs(lines: list[str], seg: list[int]) -> list[set[int]]:
    """Per segment line: the backtick run lengths on the lines after it."""
    out: list[set[int]] = []
    seen: set[int] = set()
    for i in reversed(seg):
        out.append(set(seen))
        seen |= {len(m.group()) for m in _RUN_RE.finditer(lines[i])}
    return out[::-1]


def _close_run(line: str, start: int, size: int) -> int | None:
    """End of the next run of exactly ``size`` backticks from ``start``."""
    ends = _runs_by_size(line).get(size, ())
    k = bisect_left(ends, start + size)
    return ends[k] if k < len(ends) else None


@lru_cache(maxsize=4096)
def _runs_by_size(line: str) -> dict[int, list[int]]:
    """Where each backtick run on the line ends, by its length."""
    out: dict[int, list[int]] = {}
    for m in _RUN_RE.finditer(line):
        out.setdefault(len(m.group()), []).append(m.end())
    return out


def _safe_autolink(line: str, pos: int) -> int | None:
    m = _AUTOLINK_RE.match(line, pos)
    if m is None or (m.group(1) or "").lower() in _SCRIPT_SCHEMES:
        return None
    return m.end()


def _paragraph_text(lines: list[str], seg: list[int]) -> tuple[str, list[int]]:
    """The segment's content as a paragraph sees it (container prefixes
    dropped), and per line the offset to add to a position in that line."""
    parts: list[str] = []
    offsets: list[int] = []
    at = 0
    for i in seg:
        plen = _PREFIX_RE.match(lines[i]).end()
        parts.append(lines[i][plen:])
        offsets.append(at - plen)
        at += len(lines[i]) - plen + 1
    return "\n".join(parts), offsets


class _Tails:
    """Where links' tails (destination, title) may lie in a segment's text."""

    def __init__(self, text: str) -> None:
        self.ranges: Ranges = []
        at = text.find("](")
        while at >= 0:
            m = _LINK_TAIL_RE.match(text, at, at + _WINDOW)
            if m is not None:
                self.ranges.append((m.start(), m.end()))
            elif at + _WINDOW < len(text):
                self.ranges.append((at, len(text)))  # past the window: assume a link
                break
            at = text.find("](", at + 2)
        self.starts = [a for a, _b in self.ranges]
        self.reach: list[int] = []  # reach[k]: furthest end of ranges[:k + 1]
        far = -1
        for _a, b in self.ranges:
            far = max(far, b)
            self.reach.append(far)

    def holds(self, x: int) -> bool:
        k = bisect_right(self.starts, x) - 1
        return k >= 0 and self.reach[k] > x


def _plain_spans(line: str, text: str, offset: int, tails: _Tails, table: bool,
                 ) -> tuple[Ranges, Ranges, bool]:
    """Code spans paired within ``line`` read on its own (left to right, as
    CommonMark does), its escapes and safe autolinks, and whether the line is
    *simple*: every backtick run pairs on the line, no span holds a "|" a
    table row would split it at (when the segment may hold a ``table``), and
    no run sits in inline HTML or in a link's destination or title
    (markdown-it reads links first). ``text`` is the line's segment and
    ``offset`` maps a line position into it."""
    spans: Ranges = []
    other: Ranges = []
    simple = True
    pos = 0
    while pos < len(line):
        c = line[pos]
        if c == "\\" and pos + 1 < len(line):
            other.append((pos, pos + 2))
            pos += 2
            continue
        if c == "<":
            link = _safe_autolink(line, pos)
            if link is not None:
                other.append((pos, link))
                pos = link
                continue
            at = offset + pos
            end = _inline_html_end(text, at)
            if end is not None:  # backticks in a tag pair with nothing
                if end == _UNKNOWN or "`" in text[at:end]:
                    simple = False
                else:
                    pos += min(end - at, len(line) - pos)
                    continue
        elif c == "`":
            end = _RUN_RE.match(line, pos).end()
            close = _close_run(line, end, end - pos)
            if (close is not None and not (table and _TABLE_PIPE_RE.search(line, pos, close))
                    and not tails.holds(offset + pos) and not tails.holds(offset + close - 1)):
                spans.append((pos, close))
                pos = close
                continue
            simple = False
            pos = end
            continue
        pos += 1
    return spans, other, simple


def _may_hold_table(lines: list[str], seg: list[int]) -> bool:
    """Some line of the segment may be a table's header row."""
    return any(_header_row(lines, i) for i in seg[:-1])


def _strict_inert(lines: list[str], walk: _Walk) -> tuple[list[Ranges], list[Ranges]]:
    """Per line: code spans that are code in every reading, and escapes and
    safe autolinks (inert in every reading).

    Spans count only in a segment where every line is simple (see
    _plain_spans). Anything else can re-pair them: a run that may pair with
    one on a later line (C1), a table row splitting a span at "|" (C-A), a
    backtick inside raw HTML, or markdown-it's backtick cache, which after
    one opener finds no closer may take a later opener for text even though
    its closer follows (``x ```` `y```z` ```<img>```)."""
    spans: list[Ranges] = [[] for _ in lines]
    other: list[Ranges] = [[] for _ in lines]
    for seg in _segments(lines, walk):
        text, offsets = _paragraph_text(lines, seg)
        tails, table = _Tails(text), _may_hold_table(lines, seg)
        found = [_plain_spans(lines[i], text, offsets[k], tails, table)
                 for k, i in enumerate(seg)]
        simple = all(ok for _s, _o, ok in found)
        for i, (line_spans, line_other, _ok) in zip(seg, found, strict=True):
            other[i] = line_other
            if simple:
                spans[i] = line_spans
    return spans, other


def _lenient_inert(lines: list[str], walk: _Walk) -> list[Ranges]:
    """Per line: whatever some pairing of the paragraph's backtick runs takes
    for code, plus escapes and safe autolinks. In a simple segment the
    pairing is the plain one; otherwise any run may be text or open a span
    closed by the next run of its length (every reading, markdown-it's
    included, is one of these)."""
    out: list[Ranges] = [[] for _ in lines]
    for seg in _segments(lines, walk):
        text, offsets = _paragraph_text(lines, seg)
        tails, table = _Tails(text), _may_hold_table(lines, seg)
        found = [_plain_spans(lines[i], text, offsets[k], tails, table)
                 for k, i in enumerate(seg)]
        if all(ok for _s, _o, ok in found):
            for i, (line_spans, line_other, _ok) in zip(seg, found, strict=True):
                out[i] = line_spans + line_other
            continue
        later = _later_runs(lines, seg)
        open_states: set[int] = set()  # run lengths of spans that may still be open
        for k, i in enumerate(seg):
            out[i] = found[k][1] + _any_pairing(lines[i], open_states, later[k])
    return out


def _any_pairing(line: str, open_states: set[int], later: set[int]) -> Ranges:
    """What may be code on ``line`` when any run may open a span or stay
    text; updates ``open_states`` to the spans that may run past it."""
    runs = [(m.start(), m.end()) for m in _RUN_RE.finditer(line)]
    after: list[set[int]] = [set(later)]  # after[r]: run lengths after run r on
    for a, b in reversed(runs):
        after.append(after[-1] | {b - a})
    after.reverse()
    states = {0} | open_states  # 0: no span open (a paragraph may start here)
    ranges: Ranges = []
    pos = 0
    for r, (a, b) in enumerate(runs):
        if len(states) > 1 or 0 not in states:
            ranges.append((pos, a))
        size, nxt = b - a, set()
        slashes = a - len(line[:a].rstrip("\\"))
        opens = size - slashes % 2  # outside code, "\`" is an escaped backtick
        for state in states:
            if state == 0:
                nxt.add(0)
                if opens and opens in after[r + 1]:
                    nxt.add(opens)
            else:
                nxt.add(0 if state == size else state)
        states, pos = nxt, a
    if len(states) > 1 or 0 not in states:
        ranges.append((pos, len(line)))
    open_states.clear()
    open_states.update(states - {0})
    return ranges


def _blank(text: str, ranges: Ranges) -> str:
    if not ranges:
        return text
    chars = list(text)
    for start, end in ranges:
        chars[start:end] = " " * len(chars[start:end])
    return "".join(chars)


def _keep_lt(text: str, keep: set[int]) -> str:
    """``text`` with every "<" not in ``keep`` blanked."""
    return "".join(" " if c == "<" and p not in keep else c for p, c in enumerate(text))


# ── the two readings ──────────────────────────────────────────────────────

@dataclass
class _After:
    """One line of the after text, read strictly."""

    code: bool
    scan: str = ""  # R15: code blanked, "<x " in front inside an open tag
    live: str = ""  # as scan, but only "<" that may start inline HTML
    live_cont: bool = False
    url: str = ""  # code spans blanked, for script links


def _read_after(lines: list[str]) -> tuple[list[_After], _Walk]:
    """The after text, read strictly (R16)."""
    walk = _walk(lines)
    spans, other = _strict_inert(lines, walk)
    valid = _inline_html(lines, walk)[0]
    out: list[_After] = []
    tag_open = live_open = False
    for i, line in enumerate(lines):
        if walk.kind[i] == _FENCE:
            out.append(_After(code=True))
            continue
        # HTML-block lines (in any reading) and untrusted fences: no code (C2)
        raw = walk.block[i] is not None or walk.kind[i] == _NESTED
        text = line if raw else _blank(line, spans[i] + other[i])
        scan = "<x " + text if tag_open else text
        tag_open = tag_left_open(scan)
        live_text = text if raw else _keep_lt(text, valid[i])
        live = "<x " + live_text if live_open else live_text
        out.append(_After(False, scan, live, live_open, line if raw else _blank(line, spans[i])))
        live_open = tag_left_open(live)
    return out, walk


def _inline_html(lines: list[str], walk: _Walk) -> tuple[list[set[int]], list[set[int]]]:
    """Per line: the "<" that may start inline HTML (judged over the rest of
    its segment: a tag may span the lines of a paragraph), and every "<"
    such HTML may hold, which reaches the browser raw."""
    starts: list[set[int]] = [set() for _ in lines]
    inside: list[set[int]] = [set() for _ in lines]
    for seg in _segments(lines, walk):
        text, offsets = _paragraph_text(lines, seg)
        reach = 0  # inside HTML up to here (len(text) + 1: to the segment's end)
        for k, i in enumerate(seg):
            for p, c in enumerate(lines[i]):
                if c != "<":
                    continue
                at = offsets[k] + p
                if at < reach:
                    inside[i].add(p)
                end = _inline_html_end(text, at)
                if end is not None:
                    starts[i].add(p)
                    reach = max(reach, len(text) + 1 if end == _UNKNOWN else end)
    return starts, inside


def _valid_in_line(line: str, text: str, *, autolinks: bool = False) -> set[int]:
    """The "<" in ``text`` that start inline HTML within ``line`` itself, and
    stay whole if the line is a table row (cells split at "|")."""
    def whole(p: int) -> bool:
        end = _inline_html_end(line, p) or 0
        return end > 0 and "|" not in line[p:end]

    return {p for p, c in enumerate(text) if c == "<" and (
        whole(p) or (autolinks and _AUTOLINK_RE.match(line, p)))}


# The tail of a link or image: destination and title may each sit on the next
# line, and neither renders as HTML.
_LINK_TAIL_RE = re.compile(
    r"""\]\(\s*(?P<dest><[^<>\n]*>|(?:[^\s()\\]|\\.|\([^\s()]*\))*)"""
    r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^()]*\)))?\s*\)"""
)
_LABEL_START_RE = re.compile(r"(?<![!\\])\[[^\[\]\n]*$")


def _link_hidden(lines: list[str], walk: _Walk, code: list[Ranges],
                 ) -> tuple[list[Ranges], list[list[int]]]:
    """Per line: what a link's destination or title, or an image's alt text,
    may hide (markdown-it escapes both); and where the script links that
    surely render start: a whole link on one line, outside code and any other
    link. Near-linear in the segment: ranges are sorted and merged."""
    hidden_by_line: list[Ranges] = [[] for _ in lines]
    links: list[list[int]] = [[] for _ in lines]
    for seg in _segments(lines, walk):
        text, offsets = _paragraph_text(lines, seg)
        hidden: Ranges = []
        tails: list[re.Match[str]] = []
        tail_starts: list[int] = []
        at = text.find("](")
        while at >= 0:
            m = _LINK_TAIL_RE.match(text, at, at + _WINDOW)
            if m is not None:
                hidden.append((m.start(), m.end()))
                tails.append(m)
                tail_starts.append(at)
            elif at + _WINDOW < len(text):
                hidden.append((at, len(text)))  # past the window: assume a link
                tail_starts.append(at)
                break  # hidden to the segment's end: nothing after can count
            at = text.find("](", at + 2)
        at = text.find("![")
        while at >= 0:
            k = bisect_left(tail_starts, at)
            if k < len(tail_starts):
                hidden.append((at, tail_starts[k]))
            at = text.find("![", at + 2)
        hidden.sort()
        _spread(_merged(hidden), seg, offsets, lines, hidden_by_line)
        # reach[k]: the furthest end of the ranges starting before starts[k]
        starts = [a for a, _b in hidden]
        reach, far = [], -1
        for _a, b in hidden:
            reach.append(far)
            far = max(far, b)
        content_starts = [offsets[k] + _PREFIX_RE.match(lines[i]).end() for k, i in enumerate(seg)]
        for m in tails:
            k = bisect_left(starts, m.start())
            if "\n" in m.group() or (k < len(reach) and reach[k] > m.start()):
                continue  # spans lines, or inside another link's tail or alt text
            kk = bisect_right(content_starts, m.start()) - 1
            i, pos = seg[kk], m.start() - offsets[kk]
            label = _LABEL_START_RE.search(lines[i], 0, pos)
            dest = _decode(m.group("dest").lstrip("<"))
            if (label is not None and _BAD_VALUE_RE.match(dest)
                    and not any(a < pos + len(m.group()) and label.start() < b
                                for a, b in code[i])):
                links[i].append(label.start())
    return hidden_by_line, links


def _merged(ranges: Ranges) -> Ranges:
    """Sorted ``ranges`` with overlapping ones joined."""
    out: Ranges = []
    for a, b in ranges:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _spread(ranges: Ranges, seg: list[int], offsets: list[int], lines: list[str],
            by_line: list[Ranges]) -> None:
    """Map disjoint, sorted segment ranges onto its lines."""
    line_starts = [offsets[k] + _PREFIX_RE.match(lines[i]).end() for k, i in enumerate(seg)]
    for start, end in ranges:
        for kk in range(max(bisect_right(line_starts, start) - 1, 0), len(seg)):
            i = seg[kk]
            if line_starts[kk] >= end:
                break
            lo, hi = max(start - offsets[kk], 0), min(end - offsets[kk], len(lines[i]))
            if lo < hi:
                by_line[i].append((lo, hi))


# One container marker (and the single space that belongs to it).
_ONE_MARKER_RE = re.compile(r"[ \t]{0,3}(?:> ?|(?:[-+*]|\d{1,9}[.)])(?:[ \t]|$))")


def _indented_code(line: str) -> bool:
    """Indented 4 columns or more inside its containers: code after a blank line."""
    rest = line
    while True:
        cols = 0
        for c in rest:
            if c == " ":
                cols += 1
            elif c == "\t":
                cols += 4 - cols % 4
            else:
                break
        if cols >= 4 and not _blank_line(rest):
            return True
        m = _ONE_MARKER_RE.match(rest)
        if m is None or not m.end():
            return False
        rest = rest[m.end():]


def _container_markers(line: str) -> tuple[str, ...]:
    """The line's own container markers: ">" for a quote, "-" for any list item."""
    out: list[str] = []
    rest = line
    while (m := _ONE_MARKER_RE.match(rest)) is not None and m.end():
        out.append(">" if ">" in m.group() else "-")
        rest = rest[m.end():]
    return tuple(out)


def _deep_container_code(line: str) -> bool:
    """Indented 4 columns or more, then a container marker, then code: inside
    a list item the marker may open a quote or sub-list (its indent counts
    from the item's content, not column 0), whose content is code (I-A2)."""
    stripped = line.lstrip(" \t")
    if not _indented_code(line[:len(line) - len(stripped)] + "x"):
        return False  # 1-3 columns: _container_markers sees the marker
    return _ONE_MARKER_RE.match(stripped) is not None and _indented_code(stripped)


def _starts_paragraph_text(line: str) -> bool:
    """Surely paragraph text: a letter after container markers and at most 3 spaces."""
    rest = line
    while (m := _ONE_MARKER_RE.match(rest)) is not None and m.end():
        rest = rest[m.end():]
    content = rest.lstrip(" ")
    return len(rest) - len(content) <= 3 and content[:1].isalpha()


def _read_before(lines: list[str]) -> tuple[list[Counter[str]], _Walk]:
    """Per line, the live HTML (and script links) every reading renders."""
    walk = _walk(lines)
    code = _lenient_inert(lines, walk)
    hidden, links = _link_hidden(lines, walk, code)
    spans = [c + h for c, h in zip(code, hidden, strict=True)]
    definitions = _maybe_definitions(lines, walk)
    texts: list[str | None] = []  # None: inert
    para = False  # the line above is surely paragraph text
    markers: tuple[str, ...] = ()  # the container markers of the line above
    for i, line in enumerate(lines):
        # Indented content continues a paragraph only inside the same
        # containers; a new quote or list item starts a block (I-A).
        own = _container_markers(line)
        continues = para and own == markers and "-" not in own
        markers = own
        if walk.kind[i] != _TEXT or i in definitions or (
                walk.block[i] is not True and (
                    (not continues and _indented_code(line)) or _deep_container_code(line))):
            texts.append(None)
        elif walk.block[i]:
            texts.append(line)
        else:
            texts.append(_blank(line, spans[i]))
        para = (texts[-1] is not None and walk.block[i] is None and not _blank_line(line)
                and (_starts_paragraph_text(line) or (para and _indented_code(line))))
    live: list[str | None] = []
    url: list[str | None] = []
    for i, text in enumerate(texts):
        if text is None or walk.block[i]:
            live.append(text)
            url.append(text)
        else:  # paragraph text: CommonMark escapes a "<" that starts no inline HTML
            live.append(_keep_lt(text, _valid_in_line(lines[i], text)))
            url.append(_keep_lt(text, _valid_in_line(lines[i], text, autolinks=True)))
    inert, url_inert = _browser_inert(lines, *_raw_marks(lines, walk, texts))
    counts: list[Counter[str]] = []
    for i, text in enumerate(live):
        if text is None:
            counts.append(Counter())
            continue
        counts.append(_counts(_blank(text, inert[i]), cont=False))
        url_text = _decode(_blank(url[i], url_inert[i]))
        # a link the browser reads as raw text or a comment counts for nothing (m-B)
        surely = sum(1 for p in links[i] if not any(a <= p < b for a, b in inert[i]))
        counts[-1][JS_URL] = _tag_js_urls(url_text) + (
            0 if walk.block[i] is not None else surely + len(_AUTOLINK_JS_URL_RE.findall(url_text)))
    return counts, walk


# A link reference definition; its label, destination and title may each
# continue on the next line.
_DEFINITION_RE = re.compile(rf"^{_PREFIX}\[(?:\\.|[^\]\\]){{1,999}}\]:", re.MULTILINE)


def _maybe_definitions(lines: list[str], walk: _Walk) -> set[int]:
    """Lines a reference definition may take: from where one may start to the
    end of its segment. markdown-it renders none of it."""
    out: set[int] = set()
    for seg in _segments(lines, walk):
        text = "\n".join(lines[i] for i in seg)
        m = _DEFINITION_RE.search(text)
        if m is not None:
            out.update(seg[text.count("\n", 0, m.start()):])
    return out


def _raw_marks(lines: list[str], walk: _Walk, texts: list[str | None],
               ) -> tuple[list[set[int]], list[set[int] | None]]:
    """Per line: the "<" some reading emits raw (each may open a tag, comment
    or raw text in the browser), and the characters every reading emits raw
    (None: all of them). markdown-it escapes ``< > " &`` elsewhere, so only
    these can close what a "<" opened."""
    code, escapes = _strict_inert(lines, walk)
    starts, inside = _inline_html(lines, walk)
    openers: list[set[int]] = []
    closers: list[set[int] | None] = []
    for i, line in enumerate(lines):
        if walk.kind[i] == _FENCE:
            openers.append(set())
        elif walk.block[i] is not None:
            openers.append({p for p, c in enumerate(line) if c == "<"})
        else:
            surely_text = {p for a, b in code[i] + escapes[i] for p in range(a, b)}
            openers.append((starts[i] | inside[i]) - surely_text)
        text = texts[i]
        if walk.block[i] is True:
            closers.append(None)
        elif text is None:
            closers.append(set())
        else:
            closers.append({p for a in _valid_in_line(line, text)
                            for p in range(a, _inline_html_end(line, a))})
    return openers, closers


# Elements whose content the browser never parses as markup.
_RAW_TEXT = frozenset({
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes",
    "noscript", "template", "plaintext",
})
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "xlink:href", "data"})
_TAG_NAME_RE = re.compile(r"<(/?)([A-Za-z][^\s/>]*)")
_ATTR_NAME_RE = re.compile(r"([^\s/>=\"']+)\s*$")


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class _Tokens:
    """The note as the browser's tokenizer meets it: which "<" may open
    something, and which characters may close it."""

    def __init__(self, lines: list[str], openers: list[set[int]],
                 closers: list[set[int] | None]) -> None:
        self.text = "\n".join(lines)
        self.folded = self.text.translate(_ASCII_LOWER)  # tag names are ASCII
        self.starts: list[int] = []
        self.opens: list[int] = []
        self.raw = bytearray(len(self.text))
        at = 0
        for line, opens, close in zip(lines, openers, closers, strict=True):
            self.starts.append(at)
            self.opens.extend(sorted(at + p for p in opens))
            for p in range(len(line)) if close is None else close:
                self.raw[at + p] = 1
            at += len(line) + 1

    def closes(self, p: int) -> bool:
        return bool(self.raw[p]) or self.text[p] == "'"  # markdown-it never escapes '

    def find(self, sub: str, start: int) -> int:
        """The next ``sub`` whose last character every reading emits raw."""
        while (p := self.folded.find(sub, start)) >= 0:
            if self.closes(p + len(sub) - 1):
                return p
            start = p + 1
        return len(self.text)


def _browser_inert(lines: list[str], openers: list[set[int]], closers: list[set[int] | None],
                   ) -> tuple[list[Ranges], list[Ranges]]:
    """Per line: what the browser may read as a comment, raw text or a quoted
    attribute value (across lines and blocks), and the same minus the values
    of URL attributes. It over-reads on purpose: that only makes the before
    text less live.

    Which of the "<" the tokenizer really enters depends on what came before
    (an opener can swallow the next one), so each is followed on its own and
    what any of them hides counts."""
    tokens = _Tokens(lines, openers, closers)
    text, size = tokens.text, len(tokens.text)
    found: list[tuple[int, int, bool]] = []  # start, end, is a URL value
    for lt in tokens.opens:
        if text.startswith("<!--", lt):
            end = tokens.find("-->", lt + 4)
            found.append((lt + 4, end, False))
        elif text.startswith(("<!", "<?"), lt):
            end = tokens.find(">", lt + 2)
            found.append((lt + 2, end, False))
        elif (m := _TAG_NAME_RE.match(text, lt)) is not None:
            after = _tag_body(tokens, m.end(), found)
            name = m.group(2).lower()
            if after is None:  # never closed: take all after it as hidden
                end = size
                found.append((lt + 1, end, False))
            elif m.group(1) or name not in _RAW_TEXT:
                continue
            else:
                end = size if name == "plaintext" else tokens.find(f"</{name}", after)
                found.append((after, end, False))
        else:
            continue
        if end >= size:
            break  # hidden to the end: later openers hide nothing more
    inert: list[Ranges] = [[] for _ in lines]
    url_inert: list[Ranges] = [[] for _ in lines]
    for start, end, is_url in found:
        for k in range(bisect_right(tokens.starts, start) - 1, len(lines)):
            if tokens.starts[k] > end:
                break
            piece = (max(start, tokens.starts[k]) - tokens.starts[k], end - tokens.starts[k])
            inert[k].append(piece)
            if not is_url:
                url_inert[k].append(piece)
    return inert, url_inert


def _tag_body(tokens: _Tokens, i: int, found: list[tuple[int, int, bool]]) -> int | None:
    """Scan a tag's attributes from ``i``; returns the index after its ">"
    (None: never closed)."""
    text, start = tokens.text, i
    while i < len(text):
        c = text[i]
        if c == ">" and tokens.closes(i):
            return i + 1
        if c == "<":
            found.append((i, i + 1, False))  # starts nothing inside a tag
        elif c == "=":
            j = i + 1
            while j < len(text) and text[j] in " \t\n\r\f":
                j += 1
            if j < len(text) and text[j] in "\"'":
                end = tokens.find(text[j], j + 1)
                name = _ATTR_NAME_RE.search(text, max(start, i - 64), i)
                found.append((j + 1, end, name is not None and name.group(1).lower() in _URL_ATTRS))
                i = end + 1
                continue
            i = j
            continue
        i += 1
    return None


# ── script links ──────────────────────────────────────────────────────────

def _gapped(word: str) -> str:
    """``word`` with the tab/CR/LF a browser ignores in a URL allowed between letters."""
    return "[\t\r\n]*".join(re.escape(c) for c in word)


_BAD_SCHEME_GAPPED = (
    rf"[\x00-\x20]*(?:(?:{_gapped('javascript')}|{_gapped('vbscript')})[\x00-\x20]*:"
    rf"|{_gapped('data')}[\x00-\x20]*:[\x00-\x20]*{_gapped('text/html')})"
)
_URL_ATTR = r"(?:href|src|action|formaction|xlink:href|data)\s*=\s*[\"']?"
# Over the after text joined by newlines: the attribute, link, autolink and
# reference-definition forms, a definition behind ">" or a list marker, with
# its label or destination on later lines (I2).
_JOINED_JS_URL_RE = re.compile(
    rf"{_URL_ATTR}{_BAD_SCHEME_GAPPED}"
    rf"|\]\(\s*<?{_BAD_SCHEME_GAPPED}"
    rf"|<{_BAD_SCHEME_GAPPED}"
    rf"|^{_PREFIX}\[(?:\\.|[^\]\\]){{1,999}}\]:\s*<?{_BAD_SCHEME_GAPPED}",
    re.IGNORECASE | re.MULTILINE,
)
# Script links on a before line: in a tag (see _tag_js_urls), or an autolink.
# A link counts from its tail (see _link_hidden); a reference definition
# never counts: it is live only once something refers to it, so a kept one
# never excuses a script link.
_TAG_START_RE = re.compile(r"<[A-Za-z][^\s/>]*")
_ATTR_RE = re.compile(r"""([^\s/>=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]*))?""")
_BAD_VALUE_RE = re.compile(rf"[\"']?{_BAD_SCHEME_GAPPED}", re.IGNORECASE)
_AUTOLINK_JS_URL_RE = re.compile(rf"<{_BAD_SCHEME_GAPPED}[^\x00-\x20<>]*>", re.IGNORECASE)


def _decode(text: str) -> str:
    """Entities decoded as a browser does, keeping the line a line."""
    return html.unescape(text).replace("\n", "\t")


def _tag_js_urls(text: str) -> int:
    """Tags on the line whose URL attribute holds a script link. The browser
    keeps the first of two same-named attributes, so only that one counts."""
    found = 0
    pos = 0
    while (tag := _TAG_START_RE.search(text, pos)) is not None:
        pos, seen = tag.end(), set()  # a "<" inside the tag starts nothing
        while pos < len(text) and text[pos] != ">":
            attr = _ATTR_RE.match(text, pos)
            if attr is None:
                pos += 1
                continue
            name = attr.group(1).lower()
            if (name in _URL_ATTRS and name not in seen and attr.group(2)
                    and _BAD_VALUE_RE.match(attr.group(2))):
                found += 1
            seen.add(name)
            pos = attr.end()
    return found


def _after_js_urls(after: list[_After]) -> Counter[tuple[int, int]]:
    """How many script links span each ``(first, last)`` line of the after
    text, under the reading that finds the most."""
    decoded = ["" if r.code else _decode(r.url) for r in after]
    unescaped = ["" if r.code else _decode(MD_ESCAPE_RE.sub("", r.url)) for r in after]
    found: Counter[tuple[int, int]] = Counter()
    for variant in (decoded, unescaped):
        starts = []
        at = 0
        for t in variant:
            starts.append(at)
            at += len(t) + 1
        spans = Counter((bisect_right(starts, m.start()) - 1, bisect_right(starts, m.end() - 1) - 1)
                        for m in _JOINED_JS_URL_RE.finditer("\n".join(variant)))
        found |= spans  # the larger count per span
    return found


# ── the comparison ────────────────────────────────────────────────────────

def _counts(live: str, cont: bool) -> Counter[str]:
    own = live[3:] if cont else live  # "<x " only marks the open tag
    return Counter({SCRIPT: len(SCRIPT_RE.findall(live)), HANDLER: handlers(live),
                    RAW: len(RAW_TAG_RE.findall(own))})


def _same_region(before: str | None, after: str | None) -> bool:
    """A before line in front matter or an Obsidian block excuses only a line
    still there: elsewhere it may render."""
    return before is None or before == after


def markdown_findings(before: list[str] | None, after: list[str], added: list[int],
                      kept: dict[int, int]) -> set[str]:
    """What the change adds to a markdown note: ``SCRIPT``, ``HANDLER``,
    ``JS_URL`` and ``RAW``. ``added``: indices of after lines the change adds;
    ``kept``: after index -> before index of each line it keeps."""
    try:
        return _findings(before, after, added, kept)
    finally:
        _inline_html_end.cache_clear()  # keep no note text past this call


def _findings(before: list[str] | None, after: list[str], added: list[int],
              kept: dict[int, int]) -> set[str]:
    reads, walk = _read_after(after)
    found: set[str] = set()
    for j in added:  # R15: raw-HTML syntax outside code on an added line
        r = reads[j]
        if r.code:
            continue
        if SCRIPT_RE.search(r.scan):
            found.add(SCRIPT)
        if handlers(r.scan):
            found.add(HANDLER)
        if RAW_TAG_RE.search(r.scan):
            found.add(RAW)
        if js_url(after[j]):
            found.add(JS_URL)
    prior_counts, prior_walk = _read_before(before) if before is not None else ([], None)

    def prior(j: int) -> Counter[str]:
        """What was live on the before line that after line ``j`` keeps."""
        i = kept.get(j)
        if i is None or not _same_region(prior_walk.region[i], walk.region[j]):
            return Counter()
        return prior_counts[i]

    for j, r in enumerate(reads):  # R17: live after, not live before
        if not r.code:
            found.update(kind for kind, n in _counts(r.live, r.live_cont).items()
                         if n > prior(j)[kind])
    for (first, last), n in _after_js_urls(reads).items():
        if first != last or n > prior(first)[JS_URL]:  # a link across lines: new
            found.add(JS_URL)
    return found
