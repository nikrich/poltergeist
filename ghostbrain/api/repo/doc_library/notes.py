# ghostbrain/api/repo/doc_library/notes.py
"""Companion-note format: YAML frontmatter + extracted body (spec §1)."""
from __future__ import annotations

import re
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
    if path.suffix == ".md":
        notify_index(path)


def notify_index(*paths: Path) -> None:
    """Tell the A2 link index about companion-note changes (written, moved or removed
    paths). Absolute paths outside the vault are skipped; never raises."""
    try:
        from ghostbrain.paths import vault_path
        from ghostbrain.vault_index.links import note_written

        root = Path(vault_path()).resolve()
        for p in paths:
            try:
                rel = Path(p).resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                continue
            note_written(rel)
    except Exception:  # noqa: BLE001 — indexing must never fail a library write
        pass


def unique_child(folder: Path, name: str) -> Path:
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while (folder / f"{stem} ({n}){suffix}").exists():
        n += 1
    return folder / f"{stem} ({n}){suffix}"


def _candidates(name: str):
    yield name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while True:
        yield f"{stem} ({n}){suffix}"
        n += 1


def create_exclusive(folder: Path, name: str, content: bytes) -> Path:
    """Write `content` to the first free name (`name`, `name (2)`, …), claimed atomically
    with O_EXCL so concurrent same-name writers never overwrite each other."""
    for candidate in _candidates(name):
        path = folder / candidate
        try:
            f = open(path, "xb")  # noqa: SIM115 — closed below; unlink on write failure
        except FileExistsError:
            continue
        try:
            with f:
                f.write(content)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
    raise AssertionError("unreachable")


_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')
_MAX_STEM_BYTES = 200


def sanitize_filename(stem: str, ext: str) -> str:
    """A filename valid on Windows/macOS/Linux for a user-typed title (path separators
    must already have been rejected): bad characters → '-', whitespace collapsed, the stem
    trimmed to 200 UTF-8 bytes without splitting a character."""
    clean = re.sub(r"\s+", " ", _BAD_CHARS.sub("-", stem)).strip()
    raw = clean.encode("utf-8")[:_MAX_STEM_BYTES]
    clean = raw.decode("utf-8", errors="ignore").rstrip(" .").lstrip(".") or "untitled"
    return safe_filename(f"{clean}{ext}")


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip().lstrip(".")
    return base or "untitled"
