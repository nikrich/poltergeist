"""Persist agent-generated documents as styled HTML files in the vault.

Written by the chat agent's `poltergeist_write_doc` tool. Hard-scoped to
20-contexts/generated-docs/ — the agent supplies only title + html, never a
path, so it cannot write elsewhere. The app renders these to PDF on demand.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ghostbrain.paths import vault_path

GENERATED_DOCS_DIR_REL = "20-contexts/generated-docs"
MAX_HTML_BYTES = 2_000_000


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "document"


def write_doc(title: str, html: str) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if not html.strip():
        raise ValueError("html must not be empty")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError(f"html exceeds {MAX_HTML_BYTES} bytes")

    target_dir = vault_path() / GENERATED_DOCS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = target_dir / f"{stamp}-{_slug(title)}.html"
    path.write_text(html, encoding="utf-8")

    rel = path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": title}
