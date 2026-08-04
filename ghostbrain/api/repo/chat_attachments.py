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

from ghostbrain.api.repo import attachment_caption, attachment_extract
from ghostbrain.paths import vault_path

ATTACHMENTS_DIR_REL = "20-contexts/chat-attachments"
MAX_TEXT_BYTES = 1_000_000
MAX_DOC_BYTES = 20_000_000
MAX_IMAGE_BYTES = 20_000_000

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


def _classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text"
    if attachment_caption.is_image(filename, mime):
        return "image"
    return attachment_extract.classify(filename, mime)  # "pdf" | "docx" | None


def _cap_for(kind: str) -> int:
    if kind == "text":
        return MAX_TEXT_BYTES
    if kind == "image":
        return MAX_IMAGE_BYTES
    return MAX_DOC_BYTES


def _text_body(filename: str, content: bytes) -> str:
    text = content.decode("utf-8")  # may raise UnicodeDecodeError (caught by caller)
    ext = Path(filename).suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "")
    if ext in (".md", ".markdown"):
        return text
    return f"```{lang}\n{text}\n```" if lang else text


def _render(front: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def save_attachment(conv_id: str, filename: str, mime: str, content: bytes) -> dict:
    kind = _classify(filename, mime)
    if kind is None:
        raise UnsupportedAttachment(f"unsupported attachment type: {filename} ({mime})")

    cap = _cap_for(kind)
    if len(content) > cap:
        raise AttachmentTooLarge(f"{filename} exceeds {cap} bytes")

    note_id = hashlib.sha256(content).hexdigest()[:12]
    target_dir = vault_path() / ATTACHMENTS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)

    # Content-addressed reuse — checked BEFORE the expensive body step (image
    # captioning, doc extraction) so a duplicate upload does no extra work.
    for existing in sorted(target_dir.glob("*.md")):
        if _frontmatter_id(existing) == note_id:
            return _result(
                existing,
                title=_frontmatter_title(existing) or filename,
                kind=_frontmatter_kind(existing) or kind,
            )

    body = _build_body(kind, filename, mime, content, note_id, target_dir)

    front = {
        "id": note_id,
        "source": "chat-attachment",
        "title": filename,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conversation_id": conv_id,
        "original_filename": filename,
        "kind": kind,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    note_path = target_dir / f"{stamp}-{_slug(filename)}.md"
    note_path.write_text(_render(front, body), encoding="utf-8")
    return _result(note_path, title=filename, kind=kind)


def _build_body(
    kind: str, filename: str, mime: str, content: bytes, note_id: str, target_dir: Path
) -> str:
    if kind == "text":
        try:
            return _text_body(filename, content)
        except UnicodeDecodeError as e:
            raise UnsupportedAttachment(f"{filename} is not valid UTF-8 text") from e
    if kind == "image":
        return _image_body(filename, mime, content, note_id, target_dir)
    try:
        return attachment_extract.extract_text(filename, mime, content)
    except attachment_extract.ExtractionError as e:
        raise UnsupportedAttachment(str(e)) from e


def _image_body(
    filename: str, mime: str, content: bytes, note_id: str, target_dir: Path
) -> str:
    ext = attachment_caption.image_ext(filename, mime)
    assets = target_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    asset_path = assets / f"{note_id}{ext}"
    asset_path.write_bytes(content)
    caption = attachment_caption.caption_image(asset_path)
    caption_text = caption or "(image — no readable text extracted)"
    embed = f"![[{ATTACHMENTS_DIR_REL}/assets/{note_id}{ext}]]"
    return f"{caption_text}\n\n{embed}"


def _result(note_path: Path, *, title: str, kind: str) -> dict:
    rel = note_path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": title, "kind": kind}


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


def _frontmatter_kind(path: Path) -> str | None:
    fm = _frontmatter(path)
    return fm.get("kind") if fm else None


def title_for_path(rel_path: str) -> str:
    """Original filename stored in a chat-attachment note's frontmatter, or the
    path basename if it can't be read."""
    basename = rel_path.rsplit("/", 1)[-1]
    note = vault_path() / rel_path
    return _frontmatter_title(note) or basename


def kind_for_path(rel_path: str) -> str:
    """Attachment kind stored in the note's frontmatter, or "text" if unknown."""
    note = vault_path() / rel_path
    return _frontmatter_kind(note) or "text"
