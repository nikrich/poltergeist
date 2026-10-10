"""Content rules for AI-drafted templates (spec C4).

A draft is untrusted text, and the notes it creates are written as the user,
so B3's approval hold never sees them. These rules keep anything live out of
both the template and what it renders. Every rule reads every line of the
whole text: nothing is exempt for sitting in a code fence, inline code or a
comment, so no reader's idea of where code starts or ends matters. Where a
rule cannot tell how a reader would see a line it rejects the line: a false
alarm costs one repair turn, a miss leaks an answer.

The one URL rule: a draft may hold no URL or web address at all, in any
syntax. ``url_problems`` reads the text as every reader might decode it
(NFKC, backslash/CSS/JS escapes, HTML entities and mermaid ``#NN;`` codes,
percent-encoding, invisible characters dropped; each stage up to stable
is checked, both per line and over the whole text with line breaks
dropped) and rejects a scheme ``http: https: ftp: ws: wss: data: file:
javascript: vbscript:`` not preceded by a letter or digit (so ``metadata:``
passes; ``xhttps:`` passes too, since no reader links it), a ``//`` or
``\\`` starting a host, and ``www.``. ``http:``/``ftp:``/``ws:`` need a
character after the colon, and ``data:``/``file:`` one that isn't ``*``,
so the ``file:`` key and a ``**Data:**`` label pass.

=====================  ========================================================
Rule                   Vector it covers
=====================  ========================================================
``url_problems``       any URL or web address, anywhere, however encoded
``_HTML_RULES``        script/iframe/… tags, ``on…=`` handlers, ``javascript:``
``_RAW_TAG_RE``        any raw HTML or ``<…>`` link (``<`` + letter, ``/``,
                       ``!``, ``?``), so ``<img>``, ``<a href>``, comments
``_CLICK_RE``          mermaid ``click`` actions (callbacks run code)
``_DIAGRAM_META_RE``   mermaid ``@{ img:/icon: … }`` shape images and icons
``_placeholder_links`` link/definition destinations holding a placeholder or
                       not on their line; emails built from placeholders
``ALLOWED_FENCES``     code blocks other than query/mermaid/text/markdown
``_unclosed_fence``    a code block never closed (reject-only, skips nothing)
``literal_problems``   ``format``/``default`` literals holding markup characters
``prompt_value_…``     prompt defaults / choice options holding markup
``structure_…``        duplicate keys, ``<<`` merge keys, a second ``---``
                       block; URLs in any frontmatter value as YAML reads it
``control_problems``   CR, BOM, NUL, U+2028/9: text parsers split differently
=====================  ========================================================
"""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote

import yaml

from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic, Template
from ghostbrain.vault_write import html_live
from ghostbrain.vault_write.text import parse_note

ALLOWED_FENCES = frozenset({"", "query", "mermaid", "text", "markdown", "md"})

URL_MESSAGE = "templates must not contain URLs or web addresses"
PLACEHOLDER_URL = "links can't be built from placeholders (answers would leave the vault)"

_FENCE_OPEN_RE = re.compile(r"(?:`{3,}|~{3,})[ \t]*([^\s`]*)")
_HTML_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\s*(script|iframe|object|embed|style|link|meta|form)\b", re.IGNORECASE),
     "HTML <{0}> tags are not allowed in a template"),
    # [^<>] keeps the scan linear; a "<" inside a tag is raw HTML anyway.
    (re.compile(r"<[^<>]*\son[a-z]+\s*=", re.IGNORECASE), "HTML event handlers (on…=) are not allowed"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: links are not allowed"),
)
_RAW_TAG_RE = re.compile(r"<[A-Za-z!/?]")
_CLICK_RE = re.compile(
    r"^\s*click\s+\S+\s+(?:href\b|call\b|callback\b|[\"'])"
    r"|(?-i:^\s*click\s+\S+\s+[A-Za-z_$][\w$]*\s*(?:\"[^\"]*\"\s*)?$)",  # click A fn
    re.IGNORECASE,
)
# Mermaid shape metadata A@{ … }, across lines, and the keys that load media.
_DIAGRAM_META_RE = re.compile(r"@\{[^}]*")
_RESOURCE_KEY_RE = re.compile(r"\b(?:img|icon)\s*:", re.IGNORECASE)
_LINK_DEST_RE = re.compile(r"\]\([^)]*")  # [text](…) and ![alt](…) destinations
_LINK_OPEN_AT_END_RE = re.compile(r"\]\(\s*<?\s*$")
_DEFINITION_RE = re.compile(r" {0,3}\[((?:\\.|[^\]\\]){1,999})\]:(.*)$")
_PLACEHOLDER_EMAIL_RE = re.compile(r"\}\}[\w.+\-]*@[\w\-{]|[\w.+\-]@[\w.\-]*\{\{")  # GFM emails
# Mermaid's entity codes: #60; and #lt; mean "<".
_MERMAID_ENTITY_RE = re.compile(r"(?<!&)#(\d{1,7}|[a-z][a-z0-9]{1,31});", re.IGNORECASE)

# The URL rule, matched on casefolded text. "/" runs are possessive and
# must start the run, so a long run of slashes is scanned once.
_URL_HIT_RE = re.compile(
    r"(?<![a-z0-9])(?:(?:https?|ftp|wss?):(?=\S)|(?:data|file):(?=[^\s*])|(?:java|vb)script:)"
    r"|(?<![a-z0-9/])/{2,}+(?=[^\s/])"
    r"|(?<![a-z0-9])www\.(?=[^\s.])"
)
# Invisible characters readers drop or ignore inside a token: C0/C1
# controls (tab and line breaks too), soft hyphen, zero-width and bidi
# marks, word joiners, BOM, interlinear annotations and tag characters.
_INVISIBLE_RE = re.compile(
    "[\x00-\x1f\x7f-\x9f\xad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0"
    "\ufff0-\ufffb\U0001d173-\U0001d17a\U000e0000-\U000e0fff]"
)
# JS (\x68, \u0068, \u{68}), CSS (\68 ) and markdown/YAML (\:) escapes.
_BACKSLASH_RE = re.compile(
    r"\\(?:x([0-9a-f]{2})|u\{([0-9a-f]{1,6})\}|u([0-9a-f]{4})|([0-9a-f]{1,6}) ?|(.))",
    re.IGNORECASE | re.DOTALL,
)
_MAX_DECODE_ROUNDS = 5
# Characters that turn a filter's literal text into markup or an entity.
_MARKUP_CHARS = frozenset("<>&`\\")
_LITERAL_FILTERS = frozenset({"format", "default"})
# In prompt values a lone "&" (R&D) is text; an entity is not.
_VALUE_MARKUP_RE = re.compile(r"[<>`\\]|&#?[a-z0-9]+;", re.IGNORECASE)
# Characters other parsers split lines on, or that change how a file is read.
_CONTROL_RE = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f\\x85\\ufeff\\u2028\\u2029]")


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


def _unescape(m: re.Match[str]) -> str:
    hexa = next((g for g in m.groups()[:4] if g), None)
    if hexa is None:
        return m.group(5)
    code = int(hexa, 16)
    return chr(code) if code <= 0x10FFFF else ""


def _entities(text: str) -> str:
    return html.unescape(_MERMAID_ENTITY_RE.sub(_mermaid_entity, text))


_DECODERS = (
    lambda t: unicodedata.normalize("NFKC", t),
    lambda t: _INVISIBLE_RE.sub("", t),
    lambda t: _BACKSLASH_RE.sub(_unescape, t),
    _entities,
    unquote,
)


def _readings(text: str) -> list[str]:
    """``text`` and every stage of decoding it, up to stable (bounded)."""
    out = [text]
    for _ in range(_MAX_DECODE_ROUNDS):
        before = out[-1]
        for decoder in _DECODERS:
            out.append(decoder(out[-1]))
        if out[-1] == before:
            break
    return out


def url_hit(text: str) -> re.Match[str] | None:
    """The first URL or web address in any reading of ``text``."""
    for reading in _readings(text):
        folded = reading.casefold()
        m = _URL_HIT_RE.search(folded) or _URL_HIT_RE.search(folded.replace("\\", "/"))
        if m:
            return m
    return None


def _url_problem(line: int, col: int, m: re.Match[str]) -> Diagnostic:
    return _problem(line, col, f"`{m.group()}` is a URL or web address; {URL_MESSAGE}")


def url_problems(text: str) -> list[Diagnostic]:
    """One problem per line holding a URL, or one at line 1 for a URL only
    the whole text spells (a token split over lines)."""
    out = []
    for i, line in enumerate(text.split("\n")):
        m = url_hit(line)
        if m:
            raw = _URL_HIT_RE.search(line.casefold())
            out.append(_url_problem(i + 1, raw.start() + 1 if raw else 1, m))
    if not out:
        m = url_hit(text)
        if m:
            out.append(_url_problem(1, 1, m))
    return out


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
    tag = _RAW_TAG_RE.search(decoded)
    if tag and not out:
        out.append(_problem(i + 1, tag.start() + 1, "raw HTML is not allowed in a template"))
    click = _CLICK_RE.search(decoded)
    if click:
        out.append(_problem(i + 1, click.start() + 1, "diagram click actions are not allowed"))
    fence = _FENCE_OPEN_RE.match(_content(line))
    if fence and fence.group(1).lower() not in ALLOWED_FENCES:
        out.append(_problem(i + 1, 1, f"```{fence.group(1)} code blocks are not allowed in a template"))
    return out


def _placeholder_links(i: int, decoded: str) -> list[Diagnostic]:
    """A link whose destination an answer fills, or whose destination is not
    on its line (so this check could not see it)."""
    definition = _DEFINITION_RE.match(_content(decoded))
    m = next((r for r in _LINK_DEST_RE.finditer(decoded) if "{{" in r.group()), None) \
        or _PLACEHOLDER_EMAIL_RE.search(decoded)
    if m or (definition and "{{" in definition.group(2)):
        return [_problem(i + 1, m.start() + 1 if m else 1, PLACEHOLDER_URL)]
    if _LINK_OPEN_AT_END_RE.search(decoded) or (definition and not definition.group(2).strip()):
        return [_problem(i + 1, 1, "a link must have its URL on the same line")]
    return []


def _diagram_media(lines: list[str]) -> list[Diagnostic]:
    """Mermaid ``@{ img: … }`` / ``@{ icon: … }``: media mermaid loads."""
    joined = "\n".join(decode(line) for line in lines)
    return [_problem(joined.count("\n", 0, m.start()) + 1, 1,
                     "diagram images and icons are not allowed")
            for m in _DIAGRAM_META_RE.finditer(joined) if _RESOURCE_KEY_RE.search(m.group())]


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


def content_problems(text: str) -> list[Diagnostic]:
    """Everything live in a markdown text (a draft, or a note it renders)."""
    lines = text.split("\n")
    out: list[Diagnostic] = []
    for i, line in enumerate(lines):
        decoded = decode(line)
        out += _line_rules(i, line, decoded)
        out += _placeholder_links(i, decoded)
    out += _diagram_media(lines)
    out += _unclosed_fence(lines)
    out += url_problems(text)
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


def prompt_value_problems(template: Template, lines: list[str]) -> list[Diagnostic]:
    """Prompt defaults and choice options are rendered verbatim, and only one
    option is sampled, so each must be plain text (URLs in them are found by
    ``structure_problems``)."""
    out = []
    for p in template.prompts:
        for value in (p.default, *p.options):
            if value and _VALUE_MARKUP_RE.search(value):
                line = next((i + 1 for i, text in enumerate(lines) if value in text), 1)
                out.append(_problem(line, 1, f"prompt `{p.id}`: defaults and options can't "
                                             "contain HTML or markup characters"))
    return out


def structure_problems(draft: str) -> list[Diagnostic]:
    """Frontmatter other readers could see differently from C1's parser:
    duplicate keys (last one wins in PyYAML, first or error elsewhere),
    ``<<`` merge keys (applied by PyYAML, not by every reader) and a second
    ``---`` block right after the first. Also any URL in a key or value as
    YAML reads it (escapes such as ``"\\x68ttps:"`` resolved)."""
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
                    stack.append(key)
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
        elif isinstance(node, yaml.ScalarNode) and (m := url_hit(node.value)):
            mark = node.start_mark
            out.append(_url_problem(fm_line + mark.line, mark.column + 1, m))
    first = parsed.body.split("\n", 1)[0]
    if re.fullmatch(r"\s*(?:-{3,}|\.{3})\s*", first):
        body_line = (parsed.fm_head + parsed.fm_inner + parsed.fm_close + parsed.gap).count("\n") + 1
        out.append(_problem(body_line, 1, "a second --- block after the frontmatter is not allowed"))
    return out
