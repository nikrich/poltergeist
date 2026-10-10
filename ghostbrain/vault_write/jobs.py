"""Helpers for in-process worker jobs that change existing notes (slice B4).

Jobs write as ``worker:<job>`` through the single write path, so their edits
are minimal-diff, locked, snapshotted in page history and (except the
unlisted derived-metadata jobs) listed on the Changes screen. Both helpers
read the note, compute the change, and write it against the etag they read.
If the user saves in between, the write path refuses (WriteConflict) and the
helper starts over from the fresh file, so a job never overwrites an edit.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ghostbrain.vault_write.actor import Actor
from ghostbrain.vault_write.errors import MalformedNote, WriteConflict
from ghostbrain.vault_write.etag import compute_etag
from ghostbrain.vault_write.writer import WriteResult, read, resolve_safe, write

MAX_ATTEMPTS = 3


def _gave_up(rel_path: str, attempts: int) -> WriteConflict:
    return WriteConflict(None, f"{rel_path} kept changing; gave up after {attempts} attempts")


def update_fields(
    rel_path: str,
    compute: Callable[[dict[str, Any]], Mapping[str, Any]],
    *,
    actor: Actor,
    reason: str,
    bump_updated: bool = False,
    attempts: int = MAX_ATTEMPTS,
) -> WriteResult | None:
    """Set frontmatter keys. ``compute(metadata)`` returns the fields to set;
    ``{}`` means there is nothing to do (no write, ``None``)."""
    for _ in range(attempts):
        snap = read(rel_path)
        fields = dict(compute(snap.metadata()))
        if not fields:
            return None
        try:
            return write(
                rel_path, fields=fields, actor=actor, reason=reason,
                base_etag=snap.etag, bump_updated=bump_updated,
            )
        except WriteConflict:
            continue  # someone saved in between: recompute from their version
    raise _gave_up(rel_path, attempts)


def _read_text(rel_path: str) -> tuple[str | None, bytes | None]:
    try:
        data = resolve_safe(rel_path).read_bytes()
    except FileNotFoundError:
        return None, None
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError as e:
        raise MalformedNote(f"file is not valid UTF-8: {e}") from None


def rewrite_text(
    rel_path: str,
    transform: Callable[[str | None], str | None],
    *,
    actor: Actor,
    reason: str,
    attempts: int = MAX_ATTEMPTS,
) -> WriteResult | None:
    """Replace the whole text. ``transform(current or None when missing)``
    returns the new text; ``None`` or unchanged means no write. The bytes are
    written verbatim. A missing file is created (a worker create: no row)."""
    for _ in range(attempts):
        text, data = _read_text(rel_path)
        new = transform(text)
        if new is None or new == text:
            return None
        try:
            if data is None:
                return write(
                    rel_path, content=new, op="create", actor=actor, reason=reason, verbatim=True,
                )
            return write(
                rel_path, content=new, actor=actor, reason=reason,
                base_etag=compute_etag(data), verbatim=True,
            )
        except WriteConflict:
            continue
    raise _gave_up(rel_path, attempts)
