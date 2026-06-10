"""Markdown → Confluence storage-format XHTML (the export inverse of the
connector's markdownify import path). Confluence storage format accepts
standard XHTML for text/tables/code; we don't emit any <ac:*> macros in v1.

v1 limitation: python-markdown passes raw HTML in the source through
unchanged (no sanitizer), so malformed user HTML can make Confluence
reject the storage payload."""
from __future__ import annotations

import re

import markdown as md_lib

_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _flatten_wikilinks(text: str) -> str:
    """``[[path|label]]`` → ``label``; ``[[path]]`` → last path segment.
    Vault-relative paths mean nothing inside Confluence."""
    def repl(m: re.Match) -> str:
        label = m.group(2)
        return label if label else m.group(1).rsplit("/", 1)[-1]
    return _WIKILINK.sub(repl, text)


def to_storage_html(markdown_text: str) -> str:
    return md_lib.markdown(
        _flatten_wikilinks(markdown_text),
        extensions=["tables", "fenced_code"],
        output_format="xhtml",
    )
