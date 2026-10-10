"""Content rules for AI-drafted templates (spec C4).

A draft is untrusted text, and the notes it creates are written as the user,
so B3's approval hold never sees them. These rules keep anything live out of
both the template and what it renders: no HTML, no code blocks except query
and mermaid (and nothing inside a fence that loads or links anywhere), no
images that load from outside the vault, and no link whose URL is built from
placeholders, since an answer in a URL leaves the vault when it is opened.

Where a rule cannot tell how a reader would see a line, it rejects the line:
a false alarm costs one repair turn, a miss leaks an answer.
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
# CommonMark link labels are at most 999 characters.
MAX_LABEL_CHARS = 999

# Container markers (blockquote, list) and indentation in front of a line.
_PREFIX_RE = re.compile(r"(?:[ \t]*(?:>|(?:[-+*]|\d{1,9}[.)])(?=[ \t])))*[ \t]*")
_FENCE_OPEN_RE = re.compile(r"(`{3,}|~{3,})[ \t]*([^\s`]*)(.*)$")
_FENCE_CLOSE_RE = re.compile(r"(`{3,}|~{3,})[ \t]*$")
_HTML_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\s*(script|iframe|object|embed|style|link|meta|form)\b", re.IGNORECASE),
     "HTML <{0}> tags are not allowed in a template"),
    (re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE), "HTML event handlers (on…=) are not allowed"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: links are not allowed"),
)
# Anything that names a scheme, or a scheme-relative //host.
_SCHEME_RE = re.compile(r"(?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]*:(?=\S)|//", re.IGNORECASE)
# What readers turn into a link or a fetch: these schemes (with or without
# slashes, as the WHATWG parser reads https:host), //host, www., autolinks.
_LINKABLE = r"(?:(?<![a-z0-9+.\-])(?:https?|ftp|file|mailto|data|javascript|vbscript):|//|(?<![\w.])www\.)"
_URL_RE = re.compile(_LINKABLE + r"[^\s<>()\[\]\"'`]*", re.IGNORECASE)
_AUTOLINK_RE = re.compile(r"<[a-z][a-z0-9+.\-]*:[^<>\s]*>", re.IGNORECASE)
_PLACEHOLDER_URL_RES = (
    re.compile(r"\]\([^)]*?\{\{"),  # [text](…{{x}}…) and ![alt](…{{x}}…)
    re.compile(_LINKABLE + r"[^\s<>\"]*?\{\{", re.IGNORECASE),  # bare URLs
    re.compile(r"<[a-z][a-z0-9+.\-]*:[^<>]*?\{\{", re.IGNORECASE),  # <scheme:…{{x}}…>
)
_DEFINITION_RE = re.compile(r" {0,3}\[((?:\\.|[^\]\\]){1,999})\]:(.*)$")
_LINK_OPEN_AT_END_RE = re.compile(r"\]\(\s*<?\s*$")
_FENCED_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\s*img\b", re.IGNORECASE), "images are not allowed in a diagram"),
    (re.compile(r"\b(?:src|href|xlink:href)\s*=", re.IGNORECASE), "links are not allowed in a diagram"),
    (re.compile(r"^\s*click\b", re.IGNORECASE), "click actions are not allowed in a diagram"),
    (re.compile(r"\bhref\b", re.IGNORECASE), "links are not allowed in a diagram"),
    (re.compile(_LINKABLE + "|[a-z][a-z0-9+.\\-]*://", re.IGNORECASE),
     "URLs are not allowed inside a code block"),
)
# Characters that turn a filter's literal text into markup or an entity.
_MARKUP_CHARS = frozenset("<>&`\\")
_LITERAL_FILTERS = frozenset({"format", "default"})
# In prompt values a lone "&" (R&D) is text; an entity is not.
_VALUE_MARKUP_RE = re.compile(r"[<>`\\]|&#?[a-z0-9]+;", re.IGNORECASE)
# Characters other parsers split lines on, or that change how a file is read.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x85﻿  ]")

REMOTE_IMAGE = "remote images are not allowed in a template"
PLACEHOLDER_URL = "links can't be built from placeholders (answers would leave the vault)"


def _problem(line: int, col: int, message: str, code: str = "forbidden") -> Diagnostic:
    return Diagnostic(max(line, 1), max(col, 1), "error", message, code)


def decode(text: str) -> str:
    """Text as a markdown reader sees a URL in it: backslash escapes and
    HTML entities resolved."""
    return html.unescape(html_live.MD_ESCAPE_RE.sub("", text))


def _label(text: str) -> str:
    return " ".join(decode(text).split()).casefold()


def _content(line: str) -> str:
    """The line without its blockquote/list markers and indentation."""
    return line[_PREFIX_RE.match(line).end():]


def _fences(lines: list[str]) -> tuple[list[Diagnostic], set[int]]:
    """Fence-language and unclosed-fence problems, and the indices of the
    lines inside a fence. Any fence-shaped line counts, whatever container
    it sits in, so a fence can only make more lines subject to the stricter
    in-fence rules; image and link rules run on every line regardless."""
    out: list[Diagnostic] = []
    inside: set[int] = set()
    fence = ""
    opened_at = 0
    for i, line in enumerate(lines):
        content = _content(line)
        m = _FENCE_OPEN_RE.match(content)
        if m and m.group(2).lower() not in ALLOWED_FENCES:
            out.append(_problem(i + 1, 1, f"```{m.group(2)} code blocks are not allowed in a template"))
        if fence:
            close = _FENCE_CLOSE_RE.match(content)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = ""
            else:
                inside.add(i)
        elif m and not (m.group(1)[0] == "`" and "`" in m.group(3)):
            fence, opened_at = m.group(1), i
    if fence:
        out.append(_problem(opened_at + 1, 1, "this code block is never closed"))
    return out, inside


def _html_rules(lines: list[str]) -> tuple[list[Diagnostic], set[int]]:
    out: list[Diagnostic] = []
    flagged: set[int] = set()
    for n, line in enumerate(lines, start=1):
        for pattern, message in _HTML_RULES:
            m = pattern.search(line)
            if m:
                flagged.add(n)
                out.append(_problem(n, m.start() + 1,
                                    message.format(*(g.lower() for g in m.groups()))))
    return out, flagged


def _raw_html(lines: list[str], inside: set[int], flagged: set[int]) -> list[Diagnostic]:
    """Raw HTML that B3's markdown reader finds live, located best-effort
    to the lines outside fences that look like HTML."""
    if not html_live.markdown_findings(None, lines, list(range(len(lines))), {}):
        return []
    located: list[tuple[int, int]] = []
    for fenced in (False, True):  # B3 may read a fence this scan trusts as live
        for i, line in enumerate(lines):
            if (i in inside) != fenced:
                continue
            m = html_live.RAW_TAG_RE.search(line) or html_live.HANDLER_RE.search(line)
            if m or html_live.js_url(line):
                located.append((i + 1, m.start() + 1 if m else 1))
        if located:
            break
    if not located and flagged:
        return []
    return [_problem(n, col, "raw HTML is not allowed in a template")
            for n, col in located or [(1, 1)] if n not in flagged]


def _remote_definitions(lines: list[str]) -> tuple[set[str], list[Diagnostic]]:
    """Labels of reference definitions that point outside the vault, and a
    problem for each definition whose destination is not on its line."""
    remote: set[str] = set()
    out: list[Diagnostic] = []
    for i, line in enumerate(lines):
        m = _DEFINITION_RE.match(_content(line))
        if not m:
            continue
        dest = decode(m.group(2)).strip().lstrip("<").strip()
        if not dest:
            out.append(_problem(i + 1, 1, "a link definition must have its URL on the same line"))
        elif _SCHEME_RE.match(dest):
            remote.add(_label(m.group(1)))
    return remote, out


def _images(lines: list[str]) -> list[Diagnostic]:
    """Images may only point inside the vault. Fails closed: a line with
    ``![`` is rejected when anything after it names a scheme or //, when the
    alt text or destination runs onto the next line, or when it could use a
    remote reference definition."""
    remote, out = _remote_definitions(lines)
    for i, line in enumerate(lines):
        start = line.find("![")
        if start < 0:
            continue
        rest = line[start:]
        decoded = decode(rest)
        labels = _label(rest)
        if (
            _SCHEME_RE.search(decoded)
            or "]" not in rest
            or _LINK_OPEN_AT_END_RE.search(decoded)
            or any(label and label in labels for label in remote)
        ):
            out.append(_problem(i + 1, start + 1, REMOTE_IMAGE))
    return out


def _placeholder_urls(lines: list[str]) -> list[Diagnostic]:
    out = []
    for i, line in enumerate(lines):
        decoded = decode(line)
        content = _content(decoded)
        definition = _DEFINITION_RE.match(content)
        m = next((r for pattern in _PLACEHOLDER_URL_RES if (r := pattern.search(decoded))), None)
        if m or (definition and "{{" in definition.group(2)):
            out.append(_problem(i + 1, m.start() + 1 if m else 1, PLACEHOLDER_URL))
        elif _LINK_OPEN_AT_END_RE.search(decoded):
            out.append(_problem(i + 1, 1, "a link must have its URL on the same line"))
    return out


def _fenced(lines: list[str], inside: set[int]) -> list[Diagnostic]:
    out = []
    for i in sorted(inside):
        decoded = decode(lines[i])
        for pattern, message in _FENCED_RULES:
            m = pattern.search(decoded)
            if m:
                out.append(_problem(i + 1, m.start() + 1, message))
                break
    return out


def content_problems(text: str) -> list[Diagnostic]:
    """Everything live in a markdown text (a draft, or a note it renders)."""
    lines = text.split("\n")
    out, flagged = _html_rules(lines)
    fence_problems, inside = _fences(lines)
    out += fence_problems
    out += _raw_html(lines, inside, flagged)
    out += _images(lines)
    out += _fenced(lines, inside)
    out += _placeholder_urls(lines)
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
    duplicate keys (last one wins in PyYAML, first or error elsewhere) and a
    second ``---`` block right after the first."""
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
                    if key.value in seen:
                        out.append(_problem(fm_line + key.start_mark.line,
                                            key.start_mark.column + 1,
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
    decoded = decode(text)
    return {*(m.group() for m in _URL_RE.finditer(decoded)),
            *(m.group() for m in _AUTOLINK_RE.finditer(decoded))}


def dynamic_url_problems(text: str, static: Iterable[str]) -> list[Diagnostic]:
    """URLs in rendered text that the template does not spell out literally,
    i.e. URLs assembled by placeholders and filter literals."""
    known = set(static)
    out = []
    for i, line in enumerate(text.split("\n")):
        decoded = decode(line)
        for m in (*_URL_RE.finditer(decoded), *_AUTOLINK_RE.finditer(decoded)):
            if m.group() not in known:
                out.append(_problem(i + 1, m.start() + 1, PLACEHOLDER_URL))
                break
    return out
