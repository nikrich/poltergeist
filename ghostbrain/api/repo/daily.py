"""Daily-digest list from <vault>/10-daily/<date>.md."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


_DATE_STEM_LEN = len("2026-05-08")


def _walk_daily() -> list[Path]:
    vault = vault_path()
    root = vault / "10-daily"
    if not root.exists():
        return []
    # Top-level YYYY-MM-DD.md files only — skip weekly/ and by-context/.
    return [p for p in root.glob("*.md") if len(p.stem) == _DATE_STEM_LEN]


def _snippet(body: str, limit: int = 160) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---", "===", ">")):
            continue
        return line.lstrip("*-> ")[:limit]
    return ""


def _parse(path: Path) -> dict | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    date = str(fm.get("date") or path.stem)
    return {
        "id": str(fm.get("id") or path.stem),
        "date": date,
        "title": str(fm.get("title") or f"Daily digest · {date}"),
        "snippet": _snippet(post.content),
        "noteCount": int(fm.get("noteCount") or 0),
    }


def list_daily(limit: int = 50, offset: int = 0) -> dict:
    items = [p for p in (_parse(path) for path in _walk_daily()) if p is not None]
    items.sort(key=lambda d: d["date"], reverse=True)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit]}
