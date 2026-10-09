"""Byte-preserving frontmatter text operations (spec B §1 step 3).

Everything works on ``str`` decoded strictly from UTF-8 with a BOM kept as
U+FEFF, so ``parse_note(t).render() == t`` for every input and re-encoding
gives back the original bytes. Nothing the caller did not ask to change is
re-serialised: a body splice keeps the frontmatter block's exact text, and a
field edit rewrites only that key's line (or, for a multi-line value, only
that key's block).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

import yaml

from ghostbrain.vault_write.errors import MalformedNote

BOM = "\ufeff"


class _DeleteField:
    """Sentinel type: ``fields={"k": DELETE_FIELD}`` removes key ``k``."""

    def __repr__(self) -> str:
        return "DELETE_FIELD"


DELETE_FIELD: Any = _DeleteField()

# Optional leading blank lines, then an opening fence of exactly three dashes.
_OPEN_RE = re.compile(r"(?:[ \t]*\r?\n)*---[ \t]*(\r?\n)")
_CLOSE_RE = re.compile(r"-{3,}[ \t]*(?:\r?\n)?")
_GAP_RE = re.compile(r"(?:[ \t]*\r?\n)*")
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+\Z")
# A top-level `key:` line. Keys start in column 0; quoted keys allowed.
_KEY_LINE_RE = re.compile(
    r"(?P<keyfull>(?P<key>\"(?:[^\"\\\r\n]|\\.)*\"|'(?:[^'\r\n]|'')*'"
    r"|[^\s#'\"\-?:,\[\]{}&*!|>%@`][^:\r\n]*?)[ \t]*)"
    r":(?=[ \t]|\r?\n|\Z)(?P<rest>[^\r\n]*)"
)
_SEQ_RE = re.compile(r"-(?:[ \t]|\r?\n|\Z)")
_QUOTED_VALUE_RE = re.compile(
    r"(?P<val>[ \t]*(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'))(?P<comment>[ \t]+#.*)?[ \t]*"
)
_PLAIN_VALUE_RE = re.compile(r"(?P<val>.*?)(?P<comment>[ \t]+#.*)?")


def lines_of(text: str) -> list[str]:
    """Split on ``\\n`` only (``str.splitlines`` would also split on U+2028
    etc.), keeping line endings."""
    return _LINE_RE.findall(text)


@dataclass(frozen=True)
class ParsedNote:
    bom: str
    has_frontmatter: bool
    fm_head: str  # leading blank lines + opening fence line incl. EOL
    fm_inner: str  # YAML text between the fences
    fm_close: str  # closing fence line incl. its EOL (may lack one at EOF)
    gap: str  # whitespace-only lines between the closing fence and the body
    body: str
    eol: str  # "\r\n" or "\n" — the file's line ending

    @property
    def frontmatter_text(self) -> str:
        return self.bom + self.fm_head + self.fm_inner + self.fm_close

    def render(self) -> str:
        return self.frontmatter_text + self.gap + self.body


def _detect_eol(text: str) -> str:
    i = text.find("\n")
    return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def _to_eol(text: str, eol: str) -> str:
    return re.sub(r"(?<!\r)\n", "\r\n", text) if eol == "\r\n" else text


def parse_note(text: str) -> ParsedNote:
    bom = BOM if text.startswith(BOM) else ""
    rest = text[len(bom):]
    m = _OPEN_RE.match(rest)
    if m:
        offset = m.end()
        for line in lines_of(rest[m.end():]):
            if _CLOSE_RE.fullmatch(line):
                close_end = offset + len(line)
                gap_m = _GAP_RE.match(rest, close_end)
                gap = gap_m.group(0) if gap_m else ""
                return ParsedNote(
                    bom=bom,
                    has_frontmatter=True,
                    fm_head=rest[: m.end()],
                    fm_inner=rest[m.end():offset],
                    fm_close=line,
                    gap=gap,
                    body=rest[close_end + len(gap):],
                    eol=m.group(1),
                )
            offset += len(line)
    # No frontmatter — or an opening fence that never closes, which
    # python-frontmatter also treats as plain body (e.g. a leading <hr>).
    return ParsedNote(bom, False, "", "", "", "", rest, _detect_eol(rest))


def load_metadata(parsed: ParsedNote) -> dict[str, Any]:
    if not parsed.has_frontmatter:
        return {}
    try:
        data = yaml.safe_load(parsed.fm_inner)
    except yaml.YAMLError as e:
        raise MalformedNote(f"frontmatter is not valid YAML: {e}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MalformedNote("frontmatter is not a YAML mapping")
    return data


def splice_body(parsed: ParsedNote, body: str, *, ensure_newline: bool) -> ParsedNote:
    new_body = _to_eol(body, parsed.eol)
    if ensure_newline:
        new_body = new_body.rstrip("\r\n") + parsed.eol
    if not parsed.has_frontmatter:
        return replace(parsed, body=new_body)
    close = parsed.fm_close
    if not close.endswith("\n"):
        close += parsed.eol
    gap = parsed.gap
    if not gap and not parsed.body:
        gap = parsed.eol  # house style (frontmatter.dumps): one blank line
    return replace(parsed, fm_close=close, gap=gap, body=new_body)


def _key_matches(key_text: str, key: str) -> bool:
    if key_text[:1] in ("'", '"'):
        try:
            return yaml.safe_load(key_text) == key
        except yaml.YAMLError:
            return False
    return key_text == key


def find_key_block(lines: list[str], key: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` line indices of top-level ``key``'s block: the
    key line plus indented / block-sequence continuation lines. Trailing blank
    lines are not part of the block."""
    for i, line in enumerate(lines):
        m = _KEY_LINE_RE.match(line)
        if m is None or not _key_matches(m.group("key"), key):
            continue
        end = j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                j += 1
                continue
            if nxt[0] in " \t" or _SEQ_RE.match(nxt):
                end = j = j + 1
                continue
            break
        return i, end
    return None


def _dump(key: str, value: Any) -> str:
    # PyYAML defaults (width 80, block style) — byte-compatible with the
    # legacy ``frontmatter.dumps`` writers this path replaces.
    return yaml.safe_dump({key: value}, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _dumped_key(key: str) -> str:
    return _dump(key, None)[: -len(": null\n")]


def _inline_comment(rest: str) -> str:
    m = _QUOTED_VALUE_RE.fullmatch(rest) or _PLAIN_VALUE_RE.fullmatch(rest)
    return (m.group("comment") or "") if m else ""


def _render_existing(block: list[str], key: str, value: Any, eol: str) -> list[str]:
    m = _KEY_LINE_RE.match(block[0])
    assert m is not None  # find_key_block only returns spans that start on a key line
    val_part = _dump(key, value)[len(_dumped_key(key)) + 1:]  # text after the colon
    if len(block) == 1 and val_part.startswith(" ") and val_part.count("\n") == 1:
        first = block[0]
        line_eol = "\r\n" if first.endswith("\r\n") else ("\n" if first.endswith("\n") else "")
        rest = m.group("rest")
        sep = rest[: len(rest) - len(rest.lstrip(" \t"))] or " "
        return [m.group("keyfull") + ":" + sep + val_part.strip() + _inline_comment(rest) + line_eol]
    return lines_of(_to_eol(m.group("keyfull") + ":" + val_part, eol))


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def apply_fields(parsed: ParsedNote, fields: Mapping[str, Any]) -> ParsedNote:
    if not fields:
        return parsed
    if not parsed.has_frontmatter:
        live = {k: v for k, v in fields.items() if v is not DELETE_FIELD}
        if not live:
            return parsed
        inner = "".join(_to_eol(_dump(k, v), parsed.eol) for k, v in live.items())
        return replace(
            parsed,
            has_frontmatter=True,
            fm_head="---" + parsed.eol,
            fm_inner=inner,
            fm_close="---" + parsed.eol,
            gap=parsed.eol if parsed.body else "",
        )
    existing = load_metadata(parsed)
    lines = lines_of(parsed.fm_inner)
    for key, value in fields.items():
        span = find_key_block(lines, key)
        if value is DELETE_FIELD:
            if span is not None:
                del lines[span[0]:span[1]]
            continue
        if span is not None and key in existing and _same(existing[key], value):
            continue
        if span is None:
            lines.extend(lines_of(_to_eol(_dump(key, value), parsed.eol)))
        else:
            lines[span[0]:span[1]] = _render_existing(lines[span[0]:span[1]], key, value, parsed.eol)
    out = replace(parsed, fm_inner="".join(lines))
    meta = load_metadata(out)
    for key, value in fields.items():
        if value is DELETE_FIELD:
            if key in meta:
                raise MalformedNote(f"could not remove field {key!r}")
        elif meta.get(key) != value:
            raise MalformedNote(f"field {key!r} did not round-trip through YAML")
    return out
