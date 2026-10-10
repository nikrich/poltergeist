"""Revert and undo for change-log rows (spec B §5, §6; slice B2).

A revert puts a row's before-version back; undo puts its after-version back.
Both refuse when the file no longer holds what the row expects
(``ChangedSince``) unless forced. Both write as ``restore``: the version being
replaced is always snapshotted (A3: never coalesced), a history failure
refuses the write, and no change row is added, because a revert is the user's
own write (spec B §5).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ghostbrain import history, vault_write
from ghostbrain.changes import log as changes_log
from ghostbrain.changes.log import Change
from ghostbrain.vault_write import RESTORE, WriteResult, compute_etag

log = logging.getLogger("ghostbrain.changes")

CHANGED_SINCE_MESSAGE = (
    "the note changed since this change; resend with force to overwrite it "
    "(the current version stays in page history)"
)


class RevertError(Exception):
    """Base class for revert / undo failures."""


class ChangeNotFound(RevertError):
    pass


class NotRevertable(RevertError):
    pass


class VersionGone(RevertError):
    pass


class ChangedSince(RevertError):
    def __init__(self, path: str, expected: bytes | None, current: bytes | None) -> None:
        super().__init__(CHANGED_SINCE_MESSAGE)
        self.path = path
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class Flip:
    """The file at ``at`` should hold blob ``expect``; put ``target`` at ``to``.
    ``None`` means the file is (or becomes) absent."""

    at: str
    expect: str | None
    to: str
    target: str | None


@dataclass(frozen=True)
class RevertResult:
    change: Change
    path: str
    etag: str | None


_lock = threading.Lock()


def revert_flip(c: Change) -> Flip:
    return Flip(at=c.current_path, expect=c.after_blob, to=c.rel_path, target=c.before_blob)


def undo_flip(c: Change) -> Flip:
    return Flip(at=c.rel_path, expect=c.before_blob, to=c.current_path, target=c.after_blob)


def held_flip(c: Change) -> Flip:
    """A pending change (B3): its path should still hold the version it was
    proposed against; approval puts the proposal at its destination."""
    return Flip(at=c.rel_path, expect=c.before_blob, to=c.current_path, target=c.pending_bytes_blob)


def expected_state(c: Change) -> Flip | None:
    if c.status == "applied":
        return revert_flip(c)
    if c.status == "reverted":
        return undo_flip(c)
    if c.status == "pending":
        return held_flip(c)
    return None


def read_current(rel: str) -> bytes | None:
    try:
        return vault_write.resolve_safe(rel).read_bytes()
    except FileNotFoundError:
        return None


def matches_blob(data: bytes | None, blob: str | None) -> bool:
    if blob is None:
        return data is None
    return data is not None and history.blob_id(data) == blob


def drift(c: Change) -> tuple[Flip, bytes | None] | None:
    flip = expected_state(c)
    return None if flip is None else (flip, read_current(flip.at))


def changed_since(c: Change) -> bool:
    d = drift(c)
    return d is not None and not matches_blob(d[1], d[0].expect)


def _blob_bytes(blob: str | None) -> bytes | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob)
    except history.BlobNotFound:
        raise VersionGone("this version is no longer available") from None


def _text(blob: str) -> str:
    data = _blob_bytes(blob)
    assert data is not None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise NotRevertable("this version is not UTF-8 text") from None


def _apply(flip: Flip, *, force: bool, reason: str) -> WriteResult:
    text = _text(flip.target) if flip.target is not None else None  # fail before any write
    current = read_current(flip.at)
    if not matches_blob(current, flip.expect) and not force:
        try:
            expected = _blob_bytes(flip.expect)
        except VersionGone:
            expected = None
        raise ChangedSince(flip.at, expected, current)
    base = compute_etag(current) if current is not None else None
    if text is None:
        if current is None:
            return WriteResult("applied", None, None, flip.at, None)
        return vault_write.write(flip.at, op="delete", actor=RESTORE, reason=reason, base_etag=base)
    if current is None:
        return vault_write.write(
            flip.to, content=text, op="create", actor=RESTORE, reason=reason, verbatim=True,
        )
    if flip.at != flip.to:
        return vault_write.write(
            flip.at, op="move", dest=flip.to, content=text, actor=RESTORE, reason=reason,
            base_etag=base, verbatim=True,
        )
    return vault_write.write(
        flip.at, content=text, actor=RESTORE, reason=reason, base_etag=base, verbatim=True,
    )


def _transition(
    change_id: int, *, from_status: str, to_status: str, flip_of, verb: str, force: bool
) -> RevertResult:
    with _lock:
        c = changes_log.get(change_id)
        if c is None:
            raise ChangeNotFound(f"no change #{change_id}")
        if c.status != from_status:
            raise NotRevertable(f"change #{change_id} is {c.status}")
        res = _apply(flip_of(c), force=force, reason=f"{verb} change #{c.id} by {c.actor}")
        try:
            changes_log.set_status(c.id, to_status, expect=(from_status,))
            c = changes_log.get(c.id) or c
        except changes_log.ChangeLogError:
            log.exception("could not mark change #%s %s", change_id, to_status)
            changes_log.mark_degraded(f"change #{change_id} was {verb} but not marked")
    return RevertResult(c, res.path, res.etag)


def revert(change_id: int, *, force: bool = False) -> RevertResult:
    return _transition(change_id, from_status="applied", to_status="reverted",
                       flip_of=revert_flip, verb="reverted", force=force)


def undo_revert(change_id: int, *, force: bool = False) -> RevertResult:
    return _transition(change_id, from_status="reverted", to_status="applied",
                       flip_of=undo_flip, verb="re-applied", force=force)
