"""Content rules for AI-drafted templates (spec C4).

A draft is untrusted text, and the notes it creates are written as the user,
so B3's approval hold never sees them. These rules keep anything live out of
both the template and what it renders. Every rule reads every line of the
whole text, decoded first (backslash escapes, HTML entities, mermaid
``#NN;`` codes): nothing is exempt for sitting in a code fence, inline code
or a comment, so no reader's idea of where code starts or ends matters.
Where a rule cannot tell how a reader would see a line it rejects the line:
a false alarm costs one repair turn, a miss leaks an answer.

=====================  ========================================================
Rule                   Vector it covers
=====================  ========================================================
``_HTML_RULES``        script/iframe/… tags, ``on…=`` handlers, ``javascript:``
``_RAW_TAG_RE``        any raw HTML (``<`` + letter, ``/``, ``!``, ``?``), so
                       ``<img>``, ``<a href>``, comments; URI autolinks without
                       a placeholder are the one exception
``_BAD_SCHEME_RE``     ``data:``/``vbscript:`` URLs, ``//host`` (protocol-
                       relative), CSS ``url(``/``image-set(``/``@import`` and
                       mermaid ``click`` actions
``_remote_loads``      remote URLs inside any ``<…>`` (tag-agnostic), mermaid
                       ``@{ img:/icon: … }`` shape metadata and any URL in
                       ``@{…}`` or ``%%{…}%%`` (themeCSS) directives
``_images``            images, per paragraph (alt text and destinations may
                       span lines): no scheme or ``//`` after ``![``, no remote
                       URL later in the paragraph, no ``[label]`` of a remote
                       reference definition
``_definitions``       reference definitions: URL on the same line; a ``]:``
                       whose label started on an earlier line (escapes and
                       all) can't be remote
``_URL_SPANS``, …     any link, image, autolink, bare URL, email or definition
                       URL holding a ``{{placeholder}}`` (answers leave the vault)
``literal_problems``   ``format``/``default`` literals holding markup characters
``prompt_value_…``     prompt defaults / choice options holding markup or URLs
``structure_…``        duplicate keys, ``<<`` merge keys, a second ``---`` block
``_unclosed_fence``    a code block never closed (reject-only, skips nothing)
``control_problems``   CR, BOM, NUL, U+2028/9: text parsers split differently
``dynamic_url_…``      rendered URLs the template doesn't spell out literally
=====================  ========================================================
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable

import yaml

from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic, Template
from ghostbrain.vault_write import html_live
from ghostbrain.vault_write.text import parse_note

ALLOWED_FENCES = frozenset({"", "query", "mermaid", "text", "markdown", "md"})

_FENCE_OPEN_RE = re.compile(r"(?:`{3,}|~{3,})[ \t]*([^\s`]*)")
_HTML_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\s*(script|iframe|object|embed|style|link|meta|form)\b", re.IGNORECASE),
     "HTML <{0}> tags are not allowed in a template"),
    # [^<>] keeps the scan linear; a "<" inside a tag is raw HTML anyway.
    (re.compile(r"<[^<>]*\son[a-z]+\s*=", re.IGNORECASE), "HTML event handlers (on…=) are not allowed"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: links are not allowed"),
)
_RAW_TAG_RE = re.compile(r"<[A-Za-z!/?]")
# A CommonMark URI autolink, as html_live reads one.
_URI_AUTOLINK_RE = re.compile(r"<[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\x00-\x20<>]*>")
_BAD_SCHEME_RE = re.compile(
    r"(?<![a-z0-9+.\-])(?:data:(?=\S)|vbscript\s*:)"
    r"|(?<![:/\w])//(?=[^\s/])"
    r"|\b(?:url|image-set)\s*\(|@import\b"  # CSS fetches (mermaid styles, themeCSS)
    r"|^\s*click\s+\S+\s+(?:href\b|call\b|callback\b|[\"'])"  # mermaid click actions
    r"|(?-i:^\s*click\s+\S+\s+[A-Za-z_$][\w$]*\s*(?:\"[^\"]*\"\s*)?$)",  # click A fn
    re.IGNORECASE,
)
# What a browser or mermaid fetches from: http(s) with or without slashes
# (WHATWG reads https:host), ftp/file, any scheme://, and //host.
_REMOTE_RE = re.compile(
    r"(?<![a-z0-9+.\-])(?:https?|ftp|file|wss?):|[a-z][a-z0-9+.\-]*://|//", re.IGNORECASE
)
# A "<" span up to the next "<" or ">" (linear): tag-like text, whatever
# the tag. "< " not closed on its line is a comparison, not a tag.
_ANGLE_SPAN_RE = re.compile(r"<(?:[^<>\s][^<>]*>?|[^<>]*>)")
# Mermaid shape metadata A@{ … } and %%{ … }%% directives, across lines.
_MERMAID_META_RE = re.compile(r"@\{[^}]*")
_MERMAID_DIRECTIVE_RE = re.compile(r"%%\{(?:[^}]|\}(?!%%))*")
_RESOURCE_KEY_RE = re.compile(r"\b(?:img|icon)\s*:", re.IGNORECASE)
# Anything that names a scheme, or a scheme-relative //host.
_SCHEME_RE = re.compile(r"(?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]*:(?=\S)|//", re.IGNORECASE)
# What readers turn into a link or a fetch: these schemes (with or without
# slashes, as the WHATWG parser reads https:host), //host and www.
_LINKABLE = r"(?:(?<![a-z0-9+.\-])(?:https?|ftp|file|mailto|data|javascript|vbscript):|//|(?<![\w.])www\.)"
_URL_RE = re.compile(_LINKABLE + r"[^\s<>()\[\]\"'`]*", re.IGNORECASE)
# Each pattern matches greedily (linear time); a match holding "{{" is a
# URL built from a placeholder.
_URL_SPANS = (
    re.compile(r"\]\([^)]*"),  # [text](…) and ![alt](…) destinations
    re.compile(_LINKABLE + r"[^\s<]*", re.IGNORECASE),  # bare URLs, as GFM ends them
    re.compile(r"<[a-z][a-z0-9+.\-]*:[^<>]*", re.IGNORECASE),  # <scheme:…> autolinks
)
_PLACEHOLDER_EMAIL_RE = re.compile(r"\}\}[\w.+\-]*@[\w\-{]|[\w.+\-]@[\w.\-]*\{\{")  # GFM emails
_DEFINITION_RE = re.compile(r" {0,3}\[((?:\\.|[^\]\\]){1,999})\]:(.*)$")
# A "]:" whose "[" is on an earlier line: the tail of a multi-line label.
_LABEL_TAIL_RE = re.compile(r"(?:\\.|[^\[\\])*\]:(.*)$")
_LINK_OPEN_AT_END_RE = re.compile(r"\]\(\s*<?\s*$")
# Mermaid's entity codes: #60; and #lt; mean "<".
_MERMAID_ENTITY_RE = re.compile(r"(?<!&)#(\d{1,7}|[a-z][a-z0-9]{1,31});", re.IGNORECASE)
# Characters that turn a filter's literal text into markup or an entity.
_MARKUP_CHARS = frozenset("<>&`\\")
_LITERAL_FILTERS = frozenset({"format", "default"})
# In prompt values a lone "&" (R&D) is text; an entity is not.
_VALUE_MARKUP_RE = re.compile(r"[<>`\\]|&#?[a-z0-9]+;", re.IGNORECASE)
# Characters other parsers split lines on, or that change how a file is read.
_CONTROL_RE = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f\\x85\\ufeff\\u2028\\u2029]")

REMOTE_IMAGE = "remote images are not allowed in a template"
PLACEHOLDER_URL = "links can't be built from placeholders (answers would leave the vault)"


def _problem(line: int, col: int, message: str, code: str = "forbidden") -> Diagnostic:
    return Diagnostic(max(line, 1), max(col, 1), "error", message, code)


def _mermaid_entity(m: re.Match[str]) -> str:
    code = m.group(1)
    return f"&#{code};" if code.isdigit() else f"&{code};"


def decode(text: str) -> str:
    """Text as some reader may see it: backslash escapes, HTML entities and
    mermaid entity codes resolved, and the tab/CR/LF browsers drop from URLs
    removed."""
    text = _MERMAID_ENTITY_RE.sub(_mermaid_entity, html_live.MD_ESCAPE_RE.sub("", text))
    return re.sub(r"[\t\r\n]", "", html.unescape(text))


def _label(text: str) -> str:
    return " ".join(decode(text).split()).casefold()


def _content(line: str) -> str:
    """The line without its blockquote/list markers and indentation."""
    return line[html_live._PREFIX_RE.match(line).end():]


def _line_rules(i: int, line: str, decoded: str) -> list[Diagnostic]:
    out = []
    for pattern, message in _HTML_RULES:
        m = pattern.search(decoded)
        if m:
            out.append(_problem(i + 1, m.start() + 1,
                                message.format(*(g.lower() for g in m.groups()))))
    if not out and html_live.js_url(line):
        out.append(_problem(i + 1, 1, "javascript: links are not allowed"))
    tag = next((m for m in _RAW_TAG_RE.finditer(decoded)
                if not ((a := _URI_AUTOLINK_RE.match(decoded, m.start())) and "{{" not in a.group())),
               None)
    if tag and not out:
        out.append(_problem(i + 1, tag.start() + 1, "raw HTML is not allowed in a template"))
    bad = _BAD_SCHEME_RE.search(decoded)
    if bad:
        out.append(_problem(i + 1, bad.start() + 1,
                            "data:, vbscript:, url(…), //host URLs and diagram click actions are not allowed"))
    fence = _FENCE_OPEN_RE.match(_content(line))
    if fence and fence.group(1).lower() not in ALLOWED_FENCES:
        out.append(_problem(i + 1, 1, f"```{fence.group(1)} code blocks are not allowed in a template"))
    return out


def _definitions(lines: list[str]) -> tuple[set[str], list[Diagnostic]]:
    """Labels of reference definitions that point outside the vault, and a
    problem for each definition whose URL is not on its line or whose label
    started on an earlier line and points outside the vault."""
    remote: set[str] = set()
    out: list[Diagnostic] = []
    for i, line in enumerate(lines):
        content = _content(line)
        m = _DEFINITION_RE.match(content)
        tail = None if m else _LABEL_TAIL_RE.match(content)
        if m:
            raw_dest = m.group(2)
        elif tail:
            raw_dest = tail.group(1)
        else:
            continue
        dest = decode(raw_dest).strip().lstrip("<").strip()
        if not dest:
            out.append(_problem(i + 1, 1, "a link definition must have its URL on the same line"))
        elif _SCHEME_RE.match(dest):
            if m:
                remote.add(_label(m.group(1)))
            else:
                out.append(_problem(i + 1, 1, "a link label split over lines can't point "
                                              "outside the vault"))
    return remote, out


def _paragraphs(lines: list[str]) -> list[tuple[int, list[str]]]:
    """Runs of lines between whitespace-only lines, with the first index.
    Container markers don't split a run, so a run is never smaller than the
    paragraph a reader sees."""
    out: list[tuple[int, list[str]]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if out and out[-1][0] + len(out[-1][1]) == i:
            out[-1][1].append(line)
        else:
            out.append((i, [line]))
    return out


def _images(lines: list[str], remote: set[str]) -> list[Diagnostic]:
    """Images may only point inside the vault. Alt text and destinations can
    span lines within a paragraph, so the whole paragraph from the first
    ``![`` on is read: rejected when the rest of that line names any scheme
    or //, when any later line of the paragraph holds a remote URL, or when
    it holds ``[label]`` for a remote reference definition."""
    out = []
    for first, block in _paragraphs(lines):
        at = next(((j, line.find("![")) for j, line in enumerate(block) if "![" in line), None)
        if at is None:
            continue
        j, col = at
        head = decode(block[j][col:])
        tail = [decode(line) for line in block[j + 1:]]
        norm = " ".join(" ".join([head, *tail]).split()).casefold()
        if (
            _SCHEME_RE.search(head)
            or any(_REMOTE_RE.search(line) for line in tail)
            or any(label and f"[{label}]" in norm for label in remote)
        ):
            out.append(_problem(first + j + 1, col + 1, REMOTE_IMAGE))
    return out


def _remote_loads(text: str, lines: list[str]) -> list[Diagnostic]:
    """Remote URLs where something fetches them, whatever the syntax: inside
    any ``<…>`` (bar a plain URI autolink), and in mermaid shape metadata
    (``@{ img: … }``, which mermaid loads while rendering) or ``%%{…}%%``
    directives (themeCSS)."""
    out = []
    for i, line in enumerate(lines):
        decoded = decode(line)
        for m in _ANGLE_SPAN_RE.finditer(decoded):
            autolink = _URI_AUTOLINK_RE.fullmatch(m.group())
            if _REMOTE_RE.search(m.group()) and not (autolink and "{{" not in m.group()):
                out.append(_problem(i + 1, m.start() + 1, "remote URLs are not allowed in HTML"))
                break
        if ("@{" in decoded or "%%{" in decoded) and (_REMOTE_RE.search(decoded)
                                                       or _URL_RE.search(decoded)):
            out.append(_problem(i + 1, 1, "URLs are not allowed in diagram metadata or directives"))
    joined = "\n".join(decode(line) for line in lines)
    for pattern in (_MERMAID_META_RE, _MERMAID_DIRECTIVE_RE):
        for m in pattern.finditer(joined):
            span = m.group()
            if _RESOURCE_KEY_RE.search(span) or _REMOTE_RE.search(span) or _URL_RE.search(span):
                line = joined.count("\n", 0, m.start()) + 1
                out.append(_problem(line, 1, "diagram images, icons and URLs are not allowed"))
    return out


def _unclosed_fence(lines: list[str]) -> list[Diagnostic]:
    """A code block that never closes. Reject-only: no rule skips fenced
    text, so this decides nothing else and can only over-reject."""
    fence, opened = "", 0
    for i, line in enumerate(lines):
        m = re.match(r"(`{3,}|~{3,})(.*)$", _content(line))
        if not m:
            continue
        if fence:
            if m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = ""
        elif not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence, opened = m.group(1), i
    return [_problem(opened + 1, 1, "this code block is never closed")] if fence else []


def _placeholder_urls(i: int, line: str, decoded: str) -> list[Diagnostic]:
    definition = _DEFINITION_RE.match(_content(decoded))
    m = next((r for pattern in _URL_SPANS for r in pattern.finditer(decoded) if "{{" in r.group()),
             None) or _PLACEHOLDER_EMAIL_RE.search(decoded)
    if m or (definition and "{{" in definition.group(2)):
        return [_problem(i + 1, m.start() + 1 if m else 1, PLACEHOLDER_URL)]
    if _LINK_OPEN_AT_END_RE.search(decoded):
        return [_problem(i + 1, 1, "a link must have its URL on the same line")]
    return []


def content_problems(text: str) -> list[Diagnostic]:
    """Everything live in a markdown text (a draft, or a note it renders)."""
    lines = text.split("\n")
    out: list[Diagnostic] = []
    for i, line in enumerate(lines):
        decoded = decode(line)
        out += _line_rules(i, line, decoded)
        out += _placeholder_urls(i, line, decoded)
    remote, definition_problems = _definitions(lines)
    out += definition_problems
    out += _images(lines, remote)
    out += _remote_loads(text, lines)
    out += _unclosed_fence(lines)
    return out


def control_problems(text: str) -> list[Diagnostic]:
    """CR, a BOM, NUL and the other characters parsers disagree on: the
    validated text must be exactly the text every reader sees."""
    m = _CONTROL_RE.search(text)
    if m is None:
        return []
    line = text.count("\n", 0, m.start()) + 1
    return [_problem(line, m.start() - text.rfind("\n", 0, m.start()),
                     f"the template contains the control character U+{ord(m.group()):04X}; "
                     "use plain text with LF line endings")]


def literal_problems(text: str) -> list[Diagnostic]:
    """``format``/``default`` arguments are emitted verbatim; keep markup
    characters out of them whichever answers are given."""
    try:
        segments = tokenize(text)
    except TemplateLimitError:
        return []  # reported by the placeholder check
    out = []
    for seg in segments:
        if not isinstance(seg, Placeholder):
            continue
        for call in seg.filters:
            if call.name in _LITERAL_FILTERS and call.arg and _MARKUP_CHARS & set(call.arg):
                out.append(_problem(seg.line, seg.col,
                                    f"`{call.name}` text can't contain < > & ` or \\"))
    return out


def _is_live_value(value: str) -> bool:
    return bool(_VALUE_MARKUP_RE.search(value) or _URL_RE.search(decode(value)))


def prompt_value_problems(template: Template, lines: list[str]) -> list[Diagnostic]:
    """Prompt defaults and choice options are rendered verbatim, and only one
    option is sampled, so each must be plain text."""
    out = []
    for p in template.prompts:
        for value in (p.default, *p.options):
            if value and _is_live_value(value):
                line = next((i + 1 for i, text in enumerate(lines) if value in text), 1)
                out.append(_problem(line, 1, f"prompt `{p.id}`: defaults and options can't "
                                             "contain HTML, markup characters or links"))
    return out


def structure_problems(draft: str) -> list[Diagnostic]:
    """Frontmatter other readers could see differently from C1's parser:
    duplicate keys (last one wins in PyYAML, first or error elsewhere),
    ``<<`` merge keys (applied by PyYAML, not by every reader) and a second
    ``---`` block right after the first."""
    parsed = parse_note(draft)
    if not parsed.has_frontmatter:
        return []
    fm_line = parsed.fm_head.count("\n") + 1
    out = []
    try:
        root = yaml.compose(parsed.fm_inner, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        root = None  # reported by parse_template
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, yaml.MappingNode):
            seen: set[str] = set()
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode):
                    mark = key.start_mark
                    if key.value == "<<" or key.tag == "tag:yaml.org,2002:merge":
                        out.append(_problem(fm_line + mark.line, mark.column + 1,
                                            "YAML merge keys (<<) are not allowed", "yaml"))
                    elif key.value in seen:
                        out.append(_problem(fm_line + mark.line, mark.column + 1,
                                            f"duplicate key `{key.value}`", "yaml"))
                    seen.add(key.value)
                stack.append(value)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    first = parsed.body.split("\n", 1)[0]
    if re.fullmatch(r"\s*(?:-{3,}|\.{3})\s*", first):
        body_line = (parsed.fm_head + parsed.fm_inner + parsed.fm_close + parsed.gap).count("\n") + 1
        out.append(_problem(body_line, 1, "a second --- block after the frontmatter is not allowed"))
    return out


def urls(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.split("\n"):
        decoded = decode(line)
        out.update(m.group() for m in _URL_RE.finditer(decoded))
        out.update(m.group() for m in _URI_AUTOLINK_RE.finditer(decoded))
    return out


def dynamic_url_problems(text: str, static: Iterable[str]) -> list[Diagnostic]:
    """URLs in rendered text that the template does not spell out literally,
    i.e. URLs assembled by placeholders and filter literals."""
    known = set(static)
    out = []
    for i, line in enumerate(text.split("\n")):
        decoded = decode(line)
        for m in (*_URL_RE.finditer(decoded), *_URI_AUTOLINK_RE.finditer(decoded)):
            if m.group() not in known:
                out.append(_problem(i + 1, m.start() + 1, PLACEHOLDER_URL))
                break
    return out
