# ghostbrain/api/repo/doc_library/ops.py
"""Doc operations: upload, move, rename, delete, reindex, adopt (spec §2)."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from send2trash import send2trash  # noqa: F401  (used by delete/remove_orphan, Task 6)

from ghostbrain.api.repo import attachment_caption, attachment_extract, file_kinds
from ghostbrain.api.repo.doc_library import index, notes, scope
from ghostbrain.api.repo.doc_library.errors import TooLarge

log = logging.getLogger("ghostbrain.doc_library")

_NO_TEXT_IMAGE = "(image — no readable text extracted)"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pdf_pages(path: Path) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 — page count is cosmetic
        return None


def _extract(kind: str, filename: str, mime: str, path: Path) -> tuple[str, str, int | None]:
    """(body, index_status, pages). Never raises: any failure → ("", "failed", None)."""
    try:
        if kind == "opaque":
            return "", "ok", None
        if kind == "text":
            return file_kinds.text_body(filename, path.read_bytes()), "ok", None
        if kind == "image":
            return attachment_caption.caption_image(path) or _NO_TEXT_IMAGE, "ok", None
        body = attachment_extract.extract_text(filename, mime, path)
        return body, "ok", _pdf_pages(path) if kind == "pdf" else None
    except Exception as e:  # noqa: BLE001 — a broken file must never lose the original
        log.warning("indexing %s failed: %s", path.name, e)
        return "", "failed", None


def _fresh_id(folder: Path, title: str) -> str:
    known = index.all_docs()
    while True:
        doc_id = notes.new_doc_id()
        if doc_id not in known and not (folder / notes.note_name(title, doc_id)).exists():
            return doc_id


def _index_original(
    orig: Path, *, context: str, project: str | None, title: str, mime: str, kind: str, digest: str
) -> dict:
    doc_id = _fresh_id(orig.parent, title)
    body, status, pages = _extract(kind, orig.name, mime, orig)
    front: dict = {
        "doc_id": doc_id,
        "source": notes.SOURCE,
        "title": title,
        "original": orig.name,
        "kind": kind,
        "mime": mime,
        "size": orig.stat().st_size,
        "sha256": digest,
        "created": _now(),
        "context": context,
    }
    if project:
        front["project"] = project
    if pages:
        front["pages"] = pages
    front["index_status"] = status
    notes.write_atomic(orig.parent / notes.note_name(title, doc_id), notes.render(front, body))
    index.invalidate()
    return index.summary(index.get(doc_id))


def upload(
    context: str, project: str | None, folder: str, filename: str, mime: str, content: bytes
) -> dict:
    name = notes.safe_filename(filename)
    kind = file_kinds.classify(name, mime) or "opaque"
    cap = file_kinds.cap_for(kind)
    if len(content) > cap:
        raise TooLarge(f"{name} is larger than {cap // 1_000_000} MB")
    root = scope.scope_root(context, project, for_write=True)
    target = scope.resolve_in(root, folder)
    digest = hashlib.sha256(content).hexdigest()
    for e in index.all_docs().values():
        if e.context == context and e.project == (project or None) and e.front.get("sha256") == digest:
            return {**index.summary(e), "duplicate": True}
    target.mkdir(parents=True, exist_ok=True)
    orig = notes.unique_child(target, name)
    orig.write_bytes(content)
    s = _index_original(
        orig, context=context, project=project or None, title=Path(name).stem,
        mime=mime, kind=kind, digest=digest,
    )
    return {**s, "duplicate": False}
