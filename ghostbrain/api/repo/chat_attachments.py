"""Persist chat-attached files as indexed vault notes.

Attachments land under ``20-contexts/chat-attachments/`` (must be under
20-contexts so ``semantic/refresh.py`` and search pick them up). The current
chat turn references them by path; the periodic semantic refresh embeds them
later. Slice 1 handles text/markdown/code only.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

ATTACHMENTS_DIR_REL = "20-contexts/chat-attachments"
MAX_TEXT_BYTES = 1_000_000

# Extension → fenced-code language. Markdown extensions map to "" (inline as-is).
_LANG_BY_EXT = {
    ".md": "", ".markdown": "",
    ".txt": "", ".text": "", ".log": "",
    ".py": "py", ".js": "js", ".ts": "ts", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rs", ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".sh": "sh", ".rb": "rb", ".sql": "sql", ".html": "html",
    ".css": "css", ".xml": "xml", ".toml": "toml", ".ini": "ini",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "", ".tsv": "",
}
TEXT_EXTENSIONS = set(_LANG_BY_EXT)


class UnsupportedAttachment(RuntimeError):
    """File type not accepted in this slice (→ HTTP 415)."""


class AttachmentTooLarge(RuntimeError):
    """File exceeds the per-file byte cap (→ HTTP 413)."""


def _slug(name: str) -> str:
    stem = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return slug or "attachment"


def _is_text(filename: str, mime: str) -> bool:
    return Path(filename).suffix.lower() in TEXT_EXTENSIONS or mime.startswith("text/")


def _render(front: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def save_attachment(conv_id: str, filename: str, mime: str, content: bytes) -> dict:
    if not _is_text(filename, mime):
        raise UnsupportedAttachment(f"unsupported attachment type: {filename} ({mime})")
    if len(content) > MAX_TEXT_BYTES:
        raise AttachmentTooLarge(f"{filename} exceeds {MAX_TEXT_BYTES} bytes")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UnsupportedAttachment(f"{filename} is not valid UTF-8 text") from e
    note_id = hashlib.sha256(content).hexdigest()[:12]

    target_dir = vault_path() / ATTACHMENTS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)

    # Content-addressed reuse: a note whose frontmatter id matches is identical.
    for existing in sorted(target_dir.glob("*.md")):
        if _frontmatter_id(existing) == note_id:
            stored_title = _frontmatter_title(existing) or filename
            return _result(existing, stored_title)

    ext = Path(filename).suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "")
    body = text if lang == "" and ext in (".md", ".markdown") else (
        f"```{lang}\n{text}\n```" if lang else text
    )

    front = {
        "id": note_id,
        "source": "chat-attachment",
        "title": filename,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conversation_id": conv_id,
        "original_filename": filename,
        "kind": "text",
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    note_path = target_dir / f"{stamp}-{_slug(filename)}.md"
    note_path.write_text(_render(front, body), encoding="utf-8")
    return _result(note_path, filename)


def _result(note_path: Path, filename: str) -> dict:
    rel = note_path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": filename, "kind": "text"}


def _frontmatter(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _frontmatter_id(path: Path) -> str | None:
    fm = _frontmatter(path)
    return fm.get("id") if fm else None


def _frontmatter_title(path: Path) -> str | None:
    fm = _frontmatter(path)
    return fm.get("title") if fm else None
