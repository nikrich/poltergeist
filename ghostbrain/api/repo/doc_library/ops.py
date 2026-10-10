# ghostbrain/api/repo/doc_library/ops.py
"""Doc operations: upload, move, rename, delete, reindex, adopt (spec §2)."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path

from send2trash import send2trash

from ghostbrain.api.repo import attachment_caption, attachment_extract, file_kinds
from ghostbrain.api.repo.doc_library import ai_summary, index, notes, scope
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest, NotFound, TooLarge

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
            caption = attachment_caption.caption_image(path)  # "" on vision failure
            if not caption:
                return _NO_TEXT_IMAGE, "failed", None
            return caption, "ok", None
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


def _write_pending_note(
    orig: Path, doc_id: str, *, context: str, project: str | None, title: str, mime: str,
    kind: str, digest: str,
) -> None:
    """The companion note goes down BEFORE the (slow) extraction, so an in-flight
    upload is a doc with index_status "pending" — never an unclaimed original."""
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
    front["index_status"] = "pending"
    notes.write_atomic(orig.parent / notes.note_name(title, doc_id), notes.render(front, ""))
    index.invalidate()


def _finish_index(doc_id: str) -> dict:
    """Extract the pending doc's text and rewrite its note with body + final status.
    Re-reads the doc each step so a rename/move made meanwhile is kept. Any
    unexpected error leaves the note "failed", never "pending"."""
    index.mark_active(doc_id)
    try:
        e = index.get(doc_id)
        kind = str(e.front.get("kind") or "opaque")
        body, status, pages = _extract(kind, e.original.name, str(e.front.get("mime") or ""), e.original)
        index.invalidate()
        e = index.get(doc_id)
        front = {**e.front, "index_status": status}
        if pages:
            front["pages"] = pages
        notes.write_atomic(e.note, notes.render(front, body))
    except NotFound:
        index.invalidate()
        raise
    except Exception as err:  # noqa: BLE001 — degrade to "failed", keep the doc
        log.warning("finishing index of %s failed: %s", doc_id, err)
        index.invalidate()
        e = index.get(doc_id)
        notes.write_atomic(e.note, notes.render({**e.front, "index_status": "failed"}, e.body))
    finally:
        index.unmark_active(doc_id)
    return index.summary(index.get(doc_id))


def _finish_and_enqueue(doc_id: str) -> dict:
    """_finish_index, then queue an AI summary if indexing succeeded. Returns a
    fresh summary so the response shows summary_state "pending"."""
    s = _finish_index(doc_id)
    if s.get("index_status") == "ok":
        ai_summary.enqueue(doc_id)
        s = index.summary(index.get(doc_id))
    return s


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
    title = Path(name).stem
    # Pick the id before the original exists so no index scan sees it unclaimed.
    doc_id = _fresh_id(target, title)
    orig = notes.create_exclusive(target, name, content)
    index.mark_active(doc_id)  # until _finish_index takes over, the note is in flight
    try:
        _write_pending_note(
            orig, doc_id, context=context, project=project or None, title=title,
            mime=mime, kind=kind, digest=digest,
        )
    except Exception:
        # No companion note: remove the original so it is not left as an unclaimed file.
        orig.unlink(missing_ok=True)
        index.unmark_active(doc_id)
        raise
    return {**_finish_and_enqueue(doc_id), "duplicate": False}


def _with_scope(front: dict, context: str, project: str | None) -> dict:
    out = {k: v for k, v in front.items() if k != "project"}
    out["context"] = context
    if project:
        out["project"] = project
    return out


def move(doc_id: str, context: str, project: str | None, folder: str) -> dict:
    e = index.get(doc_id)
    root = scope.scope_root(context, project, for_write=True)
    dest = scope.resolve_in(root, folder)
    if dest.resolve() == e.note.parent.resolve():
        return index.summary(e)
    dest.mkdir(parents=True, exist_ok=True)
    new_note = dest / e.note.name
    if new_note.exists():
        raise Conflict(f"a note named {e.note.name} already exists there")
    new_orig = notes.unique_child(dest, e.original.name)
    # Original first, then the note; undo the original move if the note step fails.
    shutil.move(str(e.original), str(new_orig))
    try:
        front = _with_scope({**e.front, "original": new_orig.name}, context, project or None)
        notes.write_atomic(new_note, notes.render(front, e.body))
        e.note.unlink()
        notes.notify_index(e.note)
    except Exception:
        if new_note.exists() and e.note.exists():
            new_note.unlink()
        shutil.move(str(new_orig), str(e.original))
        raise
    finally:
        index.invalidate()
    return index.summary(index.get(doc_id))


def rename(doc_id: str, title: str) -> dict:
    title = title.strip()
    if not title or "/" in title or "\\" in title:
        raise InvalidRequest("title must be non-empty and contain no path separators")
    e = index.get(doc_id)
    ext = e.original.suffix
    if ext and title.lower().endswith(ext.lower()):
        title = title[: -len(ext)].strip() or title
    want = notes.sanitize_filename(title, ext)
    new_orig = e.original
    if want != e.original.name:
        new_orig = notes.unique_child(e.original.parent, want)
        e.original.rename(new_orig)
    try:
        front = {**e.front, "title": title, "original": new_orig.name}
        notes.write_atomic(e.note, notes.render(front, e.body))
    except Exception:
        if new_orig != e.original:
            new_orig.rename(e.original)
        raise
    finally:
        index.invalidate()
    return index.summary(index.get(doc_id))


def delete(doc_id: str) -> None:
    e = index.get(doc_id)
    # Note first: if the original's trash step then fails, the original is left
    # unclaimed (surfaced in attention) rather than the note dangling without a file.
    try:
        send2trash(str(e.note))
        notes.notify_index(e.note)
        send2trash(str(e.original))
    finally:
        index.invalidate()


def reindex(doc_id: str) -> dict:
    e = index.get(doc_id)
    kind = str(e.front.get("kind") or "opaque")
    body, status, pages = _extract(kind, e.original.name, str(e.front.get("mime") or ""), e.original)
    front = {**e.front, "index_status": status}
    if pages:
        front["pages"] = pages
    notes.write_atomic(e.note, notes.render(front, body))
    index.invalidate()
    if status == "ok":
        ai_summary.enqueue(doc_id)
    return index.summary(index.get(doc_id))


def adopt(context: str, project: str | None, folder: str, name: str) -> dict:
    root = scope.scope_root(context, project, for_write=True)
    d = scope.resolve_in(root, folder)
    p = d / notes.safe_filename(name)
    if not p.is_file() or (p.name.endswith(".md") and notes.read_note(p) is not None):
        raise NotFound(f"file not found: {name}")
    if p.resolve() in index.claimed_originals():
        raise Conflict(f"already claimed by a library note: {name}")
    mime = mimetypes.guess_type(p.name)[0] or ""
    kind = file_kinds.classify(p.name, mime) or "opaque"
    content = p.read_bytes()
    cap = file_kinds.cap_for(kind)
    if len(content) > cap:
        raise TooLarge(f"{p.name} is larger than {cap // 1_000_000} MB")
    doc_id = _fresh_id(p.parent, p.stem)
    index.mark_active(doc_id)
    try:
        _write_pending_note(
            p, doc_id, context=context, project=project or None, title=p.stem, mime=mime,
            kind=kind, digest=hashlib.sha256(content).hexdigest(),
        )
    except Exception:
        index.unmark_active(doc_id)
        raise
    return _finish_and_enqueue(doc_id)


def remove_orphan(doc_id: str) -> None:
    note = index.orphans().get(doc_id)
    if note is None:
        raise NotFound(f"no orphan note for {doc_id}")
    try:
        send2trash(str(note))
        notes.notify_index(note)
    finally:
        index.invalidate()
