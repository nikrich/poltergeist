# ghostbrain/api/repo/doc_library/notes.py
"""Companion-note format: YAML frontmatter + extracted body (spec §1)."""
from __future__ import annotations

import secrets
from pathlib import Path

import yaml

from ghostbrain.api.repo.notes_manual import make_slug

SOURCE = "doc-library"
KEEP = ".keep"


def new_doc_id() -> str:
    return secrets.token_hex(6)


def note_name(title: str, doc_id: str) -> str:
    return f"{make_slug(title)}-{doc_id[:6]}.md"


def render(front: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def read_note(path: Path) -> tuple[dict, str] | None:
    """(frontmatter, body) for a library companion note; None for any other file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        front = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict) or front.get("source") != SOURCE:
        return None
    return front, text[end + 4 :].lstrip("\n")


def write_atomic(path: Path, text: str) -> None:
    # Dot-prefixed tmp so a crash mid-write never shows up in tree scans.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def unique_child(folder: Path, name: str) -> Path:
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while (folder / f"{stem} ({n}){suffix}").exists():
        n += 1
    return folder / f"{stem} ({n}){suffix}"


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip().lstrip(".")
    return base or "untitled"
