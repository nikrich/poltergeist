"""The template language: ``{{ name.field | filter: arg }}`` placeholders.

Closed by design: a placeholder is a dotted name plus a chain of named
filters from the fixed registry (functions.py). There are no calls,
operators, indexing, loops or includes. Anything that is not exactly that
shape is not an expression and renders as its literal text. Hard limits
bound the work any template can cause.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TEMPLATE_CHARS = 256_000
MAX_PLACEHOLDERS = 5_000
MAX_EXPR_CHARS = 400
MAX_FILTERS = 8
MAX_NAME_DEPTH = 4

_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"', re.DOTALL)
_UNESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)


class TemplateLimitError(ValueError):
    """The source exceeds a hard size limit (a security bound, not style)."""


@dataclass(frozen=True)
class FilterCall:
    name: str
    arg: str | None


@dataclass(frozen=True)
class Placeholder:
    raw: str
    start: int
    end: int
    line: int
    col: int
    path: tuple[str, ...] | None
    filters: tuple[FilterCall, ...]


@dataclass(frozen=True)
class Text:
    text: str


Segment = Text | Placeholder


def _split_pipes(expr: str) -> list[str] | None:
    parts: list[str] = []
    buf: list[str] = []
    in_quote = escaped = False
    for ch in expr:
        if in_quote:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
            buf.append(ch)
        elif ch == "|":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if in_quote:
        return None
    parts.append("".join(buf))
    return parts


def _parse_filter(part: str) -> FilterCall | None:
    name, sep, rest = part.partition(":")
    name = name.strip()
    if not _NAME_RE.fullmatch(name):
        return None
    if not sep:
        return FilterCall(name, None)
    arg = rest.strip()
    if arg.startswith('"'):
        m = _QUOTED_RE.fullmatch(arg)
        if m is None:
            return None
        return FilterCall(name, _UNESCAPE_RE.sub(r"\1", m.group(1)))
    if not arg:
        return None
    return FilterCall(name, arg)


def parse_expression(expr: str) -> tuple[tuple[str, ...], tuple[FilterCall, ...]] | None:
    """``name(.field)* (| filter(: arg)?)*`` or None."""
    parts = _split_pipes(expr)
    if parts is None or len(parts) - 1 > MAX_FILTERS:
        return None
    names = parts[0].strip().split(".")
    if len(names) > MAX_NAME_DEPTH or not all(_NAME_RE.fullmatch(n) for n in names):
        return None
    filters: list[FilterCall] = []
    for part in parts[1:]:
        call = _parse_filter(part)
        if call is None:
            return None
        filters.append(call)
    return tuple(names), tuple(filters)


def tokenize(source: str) -> list[Segment]:
    """Split ``source`` into literal text and placeholders. Linear in the
    source size (each ``{{`` looks ahead at most MAX_EXPR_CHARS)."""
    if len(source) > MAX_TEMPLATE_CHARS:
        raise TemplateLimitError(f"template is larger than {MAX_TEMPLATE_CHARS} characters")
    out: list[Segment] = []
    text_start = search = 0
    count = 0
    line, line_start, scanned = 1, 0, 0
    while True:
        open_at = source.find("{{", search)
        if open_at < 0:
            break
        close_at = source.find("}}", open_at + 2, open_at + 4 + MAX_EXPR_CHARS)
        if close_at < 0 or "{{" in source[open_at + 2 : close_at]:
            search = open_at + 2
            continue
        count += 1
        if count > MAX_PLACEHOLDERS:
            raise TemplateLimitError(f"template has more than {MAX_PLACEHOLDERS} placeholders")
        line += source.count("\n", scanned, open_at)
        nl = source.rfind("\n", scanned, open_at)
        if nl >= 0:
            line_start = nl + 1
        scanned = open_at
        if open_at > text_start:
            out.append(Text(source[text_start:open_at]))
        end = close_at + 2
        parsed = parse_expression(source[open_at + 2 : close_at])
        path, filters = parsed if parsed is not None else (None, ())
        out.append(
            Placeholder(source[open_at:end], open_at, end, line, open_at - line_start + 1, path, filters)
        )
        text_start = search = end
    if text_start < len(source):
        out.append(Text(source[text_start:]))
    return out
