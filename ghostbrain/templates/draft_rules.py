"""Content rules for AI-drafted templates (spec C4).

A draft is untrusted text, and the notes it creates are written as the user,
so B3's approval hold never sees them. These rules keep anything live out of
both the template and what it renders. Every rule reads every line of the
whole text: nothing is exempt for sitting in a code fence, inline code or a
comment, so no reader's idea of where code starts or ends matters. Where a
rule cannot tell how a reader would see a line it rejects the line: a false
alarm costs one repair turn, a miss leaks an answer.

The one URL rule is syntax-blind: a draft may not hold ``//``, ``:/`` or
a scheme word (``http https ftp ws wss data file javascript vbscript``)
followed by optional whitespace and ``:``, unless a letter or digit comes
before the word (so ``metadata:`` passes). Prose counts: ``Raw data:``,
``**File:**``, ``// todo`` and ``C:\\Users`` (a backslash reads as a slash)
are rejected too. ``www.`` stays a hit as well. ``url_problems`` checks
every reading of the text: each stage of decoding it up to stable (NFKC,
format and control characters dropped, backslash escapes, HTML entities
and mermaid ``#NN;`` codes, percent-encoding; at most five rounds), each
also with backslashes read as slashes and with all whitespace removed. It
reads each line, then the whole text, so a hit only line breaks hide is
found too. The one exemption is the ``file:`` key of the ``template:``
mapping itself (see ``mask_file_key``).

=====================  ========================================================
Rule                   Vector it covers
=====================  ========================================================
``url_problems``       ``//``, ``:/``, a scheme word and ``:``, ``www.``:
                       anywhere, however encoded or split
``_HTML_RULES``        script/iframe/… tags, ``on…=`` handlers, ``javascript:``
``_RAW_TAG_RE``        any raw HTML or ``<…>`` link (``<`` + letter, ``/``,
                       ``!``, ``?``), so ``<img>``, ``<a href>``, comments
``_CLICK_RE``          mermaid ``click`` actions (callbacks run code)
``_DIRECTIVE_RE``      mermaid ``%%{…}%%`` directives (theme CSS, config)
``_diagram_config``    mermaid ``config:`` frontmatter (theme CSS, config)
``_DIAGRAM_META_RE``   mermaid ``@{ img:/icon: … }`` shape images and icons
``_placeholder_links`` a placeholder anywhere after ``](`` or ``]:``, a
                       destination not on its line; emails built from
                       placeholders
``ALLOWED_FENCES``     code blocks other than query/mermaid/text/markdown
``_unclosed_fence``    a code block never closed (reject-only, skips nothing)
``literal_problems``   ``format``/``default`` literals holding markup characters
``prompt_value_…``     prompt defaults / choice options holding markup
``structure_…``        duplicate keys, ``<<`` merge keys, a second ``---``
                       block; URLs in any frontmatter value as YAML reads it
``control_problems``   CR, BOM, NUL, U+2028/9: text parsers split differently
``invisible_problems`` bidi overrides, zero-width and tag characters (Cf)
=====================  ========================================================
"""
from __future__ import annotations

import functools
import html
import re
import sys
import unicodedata
from urllib.parse import unquote

import yaml

from ghostbrain.templates.lang import Placeholder, TemplateLimitError, tokenize
from ghostbrain.templates.parse import Diagnostic, Template
from ghostbrain.vault_write import html_live
from ghostbrain.vault_write.text import parse_note

ALLOWED_FENCES = frozenset({"", "query", "mermaid", "text", "markdown", "md"})

URL_MESSAGE = "templates must not contain URLs, // or :/"
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
# Mermaid %%{init: …}%% and other directives: they carry theme CSS and config.
_DIRECTIVE_RE = re.compile(r"%%\s*\{")
# Mermaid shape metadata A@{ … }, across lines, and the keys that load media.
_CONFIG_KEY_RE = re.compile(r"(?<![\w-])config[\"']?\s*:|^\W*\?\s*[\"']?config\b")
_DIAGRAM_META_RE = re.compile(r"@\{[^}]*")
_RESOURCE_KEY_RE = re.compile(r"\b(?:img|icon)\s*:", re.IGNORECASE)
# [text](…) and ![alt](…): everything after the opener, since balanced or
# escaped parentheses keep a destination going past the first ")".
_LINK_DEST_RE = re.compile(r"\]\(.*")
_LINK_OPEN_AT_END_RE = re.compile(r"\]\(\s*<?\s*$")
_DEFINITION_RE = re.compile(r" {0,3}\[((?:\\.|[^\]\\]){1,999})\]:(.*)$")
_PLACEHOLDER_EMAIL_RE = re.compile(r"\}\}[\w.+\-]*@[\w\-{]|[\w.+\-]@[\w.\-]*\{\{")  # GFM emails
# Mermaid's entity codes: #60; and #lt; mean "<".
_MERMAID_ENTITY_RE = re.compile(r"(?<!&)#(\d{1,7}|[a-z][a-z0-9]{1,31});", re.IGNORECASE)

# The URL rule, matched on casefolded text.
_SCHEME_HIT = r"(?<![a-z0-9])(?:(?:https?|ftp|wss?|data|file|javascript|vbscript)\s*+:|www\.)"
_URL_HIT_RE = re.compile(r"//|:/|" + _SCHEME_HIT)
# Only scheme words and www.: for text whose slashes stand between placeholders.
_SCHEME_HIT_RE = re.compile(_SCHEME_HIT)
_WHITESPACE_RE = re.compile(r"\s+")


def _invisible_class() -> str:
    """Format (Cf) and control (Cc) characters in this Python's Unicode
    database, plus the whole Default_Ignorable_Code_Point property (the
    grapheme joiner, Hangul fillers, variation selectors and the unassigned
    U+2065, U+FFF0-FFF8 and U+E0000-E0FFF ranges)."""
    ranges: list[list[int]] = []
    for c in range(sys.maxunicode + 1):
        if unicodedata.category(chr(c)) in ("Cf", "Cc"):
            if ranges and ranges[-1][1] == c - 1:
                ranges[-1][1] = c
            else:
                ranges.append([c, c])
    body = "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in ranges)
    return (f"[{body}\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
            "\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0"
            "\ufff0-\ufffb\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0000-\U000e0fff]")


_INVISIBLE_RE = re.compile(_invisible_class())
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


def _mermaid_codes(text: str) -> str:
    """Mermaid ``#NN;`` codes decoded left to right; a code right after an
    ``&`` it produced is left for the next HTML decode (``#amp;#58;`` reads
    ``&#58;``)."""
    parts, last, end = [], "", 0
    for m in _MERMAID_ENTITY_RE.finditer(text):
        if m.start() > end:
            parts.append(text[end:m.start()])
            last = text[m.start() - 1]
        code = m.group() if last == "&" else _mermaid_char(m.group(1))
        parts.append(code)
        last = code[-1:] or last
        end = m.end()
    parts.append(text[end:])
    return "".join(parts)


@functools.lru_cache(maxsize=1024)
def _mermaid_char(code: str) -> str:
    return html.unescape(f"&#{code};" if code.isdigit() else f"&{code};")


def _html_stable(text: str) -> str:
    """HTML entities decoded until stable (bounded): ``&amp;amp;#58;`` is
    ``:``."""
    for _ in range(_MAX_DECODE_ROUNDS):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def _mermaid_then_html(text: str) -> str:
    """Mermaid's own reading: every ``#NN;`` code made an entity at once,
    then one HTML decode."""
    return html.unescape(_MERMAID_ENTITY_RE.sub(_mermaid_entity, text))


def _strip_invisible(text: str) -> str:
    return _INVISIBLE_RE.sub("", text)


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _escapes(text: str) -> str:
    return _BACKSLASH_RE.sub(_unescape, text)


# Two orders of decoding, both read: HTML entities (once, then until
# stable) and mermaid codes as separate stages, so &amp;#58; and #amp;#58;
# read as :, and mermaid's own all-at-once reading, so #amp;#sol;#sol;
# reads as &//.
_SPLIT = (_nfkc, _escapes, html.unescape, _html_stable, _mermaid_codes, _html_stable, unquote)
_MERMAID = (_nfkc, _escapes, _mermaid_then_html, unquote)


def _chain(text: str, decoders: tuple, memo: dict) -> list[str]:
    """``text`` and each distinct stage of decoding it, up to stable
    (bounded). ``memo`` holds stage results the other chains share."""
    out = [text]
    for _ in range(_MAX_DECODE_ROUNDS):
        before = out[-1]
        for decoder in decoders:
            key = (decoder, out[-1])
            if key not in memo:
                memo[key] = decoder(out[-1])
            if memo[key] != out[-1]:
                out.append(memo[key])
        if out[-1] == before:
            break
    return out


def _readings(text: str) -> list[str]:
    """Every distinct reading along both decoding orders, invisible
    characters dropped at the start of each round. Where any reading holds
    an invisible character (a line break or tab too), also with them
    dropped after every stage and with them kept: one is a boundary, so
    a\u200bhttps&#58; reads https:. Otherwise those give the same
    readings."""
    memo: dict = {}
    out = [r for chain in (_SPLIT, _MERMAID)
           for r in _chain(text, (_strip_invisible, *chain), memo)]
    if any(_INVISIBLE_RE.search(r) for r in out):
        for chain in (_SPLIT, _MERMAID):
            out += _chain(text, tuple(s for d in chain for s in (_strip_invisible, d)), memo)
            out += _chain(text, chain, memo)
    return list(dict.fromkeys(out))


def _hit(readings: list[str], rule: re.Pattern[str] = _URL_HIT_RE) -> re.Match[str] | None:
    """The first URL rule hit in any reading, also read with backslashes as
    slashes and with all whitespace removed."""
    for reading in readings:
        folded = reading.casefold()
        slashed = folded.replace("\\", "/")
        stripped = _WHITESPACE_RE.sub("", slashed)
        for variant in (folded, slashed, stripped) if slashed != folded else (folded, stripped):
            m = rule.search(variant)
            if m:
                return m
    return None


def _url_problem(line: int, col: int, m: re.Match[str]) -> Diagnostic:
    return _problem(line, col, f"`{m.group()}` may be read as part of a URL; {URL_MESSAGE}")


def url_problems(text: str, *, slashes: bool = True) -> list[Diagnostic]:
    """One problem per line with a hit in any of its readings; else one at
    line 1 for a hit only the whole text has (split over lines). With
    ``slashes=False`` only scheme words and ``www.`` count."""
    rule = _URL_HIT_RE if slashes else _SCHEME_HIT_RE
    out = []
    for i, line in enumerate(text.split("\n")):
        m = _hit(_readings(line), rule)
        if m:
            raw = rule.search(line.casefold())
            out.append(_url_problem(i + 1, raw.start() + 1 if raw else 1, m))
    if not out:
        m = _hit(_readings(text), rule)
        if m:
            out.append(_url_problem(1, 1, m))
    return out


def mask_file_key(draft: str) -> str:
    """``draft`` with the ``file`` key of its ``template:`` mapping written as
    ``kkkk``: the only scheme word a template needs. Only a plain key whose
    value is a mapping, at the exact place YAML reads it, is masked; the
    letters only end a hit, never start one, and the value is still read."""
    parsed = parse_note(draft)
    if not parsed.has_frontmatter:
        return draft
    try:
        root = yaml.compose(parsed.fm_inner, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return draft
    offset = len(parsed.bom) + len(parsed.fm_head)
    for key, value in root.value if isinstance(root, yaml.MappingNode) else ():
        if not (isinstance(key, yaml.ScalarNode) and key.value == "template"
                and isinstance(value, yaml.MappingNode)):
            continue
        for k, v in value.value:
            start = offset + k.start_mark.index
            if (isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.MappingNode)
                    and draft[start:offset + k.end_mark.index] == "file"):
                draft = draft[:start] + "kkkk" + draft[start + 4:]
    return draft


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
    directive = _DIRECTIVE_RE.search(decoded) or _DIRECTIVE_RE.search(line)
    if directive:
        out.append(_problem(i + 1, directive.start() + 1,
                            "diagram directives are not allowed in a template"))
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


def _diagram_config(lines: list[str]) -> list[Diagnostic]:
    """A ``config`` key on any line from the first mermaid code block on:
    mermaid reads it from a diagram's own frontmatter (theme CSS, like
    ``%%{init}%%``). Reject-only, so no fence model is needed."""
    out, seen = [], False
    for i, line in enumerate(lines):
        fence = _FENCE_OPEN_RE.match(_content(line))
        seen = seen or bool(fence and fence.group(1).lower() == "mermaid")
        if seen and _CONFIG_KEY_RE.search(decode(line).casefold()):
            out.append(_problem(i + 1, 1, "diagram config is not allowed in a template"))
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


def content_problems(text: str, *, slashes: bool = True) -> list[Diagnostic]:
    """Everything live in a markdown text (a draft, or a note it renders).
    ``slashes`` as in ``url_problems``."""
    lines = text.split("\n")
    out: list[Diagnostic] = []
    for i, line in enumerate(lines):
        decoded = decode(line)
        out += _line_rules(i, line, decoded)
        out += _placeholder_links(i, decoded)
    out += _diagram_media(lines)
    out += _diagram_config(lines)
    out += _unclosed_fence(lines)
    out += url_problems(mask_file_key(text), slashes=slashes)
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


INVISIBLE_MESSAGE = "invisible formatting characters are not allowed"
# Emoji-ish characters a zero-width joiner may join (VS16 may sit before it).
_EMOJI_CATEGORIES = frozenset({"So", "Sk"})


def _joins_emoji(text: str, i: int) -> bool:
    before = text[i - 1] if i else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    return (before == "\ufe0f" or (before and unicodedata.category(before) in _EMOJI_CATEGORIES)) \
        and bool(after) and unicodedata.category(after) in _EMOJI_CATEGORIES


def invisible_problems(text: str) -> list[Diagnostic]:
    """Format characters (bidi overrides, zero-width marks, tag characters)
    can make the approval view show other text than a reader sees; one
    problem per line. A zero-width joiner inside an emoji sequence is fine;
    the BOM is reported by ``control_problems``."""
    out, last = [], 0
    for i, ch in enumerate(text):
        if ch == "\ufeff" or unicodedata.category(ch) != "Cf":
            continue
        if ch == "\u200d" and _joins_emoji(text, i):
            continue
        line = text.count("\n", 0, i) + 1
        if line != last:
            out.append(_problem(line, i - text.rfind("\n", 0, i), INVISIBLE_MESSAGE))
            last = line
    return out


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
        elif isinstance(node, yaml.ScalarNode) and (hits := url_problems(node.value)):
            mark = node.start_mark
            out.append(_problem(fm_line + mark.line, mark.column + 1, hits[0].message))
    first = parsed.body.split("\n", 1)[0]
    if re.fullmatch(r"\s*(?:-{3,}|\.{3})\s*", first):
        body_line = (parsed.fm_head + parsed.fm_inner + parsed.fm_close + parsed.gap).count("\n") + 1
        out.append(_problem(body_line, 1, "a second --- block after the frontmatter is not allowed"))
    return out
