"""Approve or reject a held change (spec B §3, §5; slice B3).

Approval re-runs the write path against the *current* file (etag check,
snapshot, atomic write, change row) as the change's own actor, with the hold
policy skipped. The pending row becomes the applied row, so B2's Revert works
on it afterwards. If the file changed since the proposal, approval refuses
(``StaleProposal`` → 409) unless forced. A forced approval snapshots the
current version first, so it stays in page history.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ghostbrain import history, vault_write
from ghostbrain.changes import log as changes_log
from ghostbrain.changes import revert as _rv
from ghostbrain.changes.log import Change
from ghostbrain.changes.revert import ChangeNotFound, Flip, RevertError, VersionGone
from ghostbrain.vault_write import WriteResult, compute_etag

log = logging.getLogger("ghostbrain.changes")

STALE_MESSAGE = (
    "the note changed since this was proposed; approve anyway to overwrite it "
    "(the current version stays in page history)"
)


class NotApprovable(RevertError):
    """The change is not waiting for approval, or cannot be written."""


class StaleProposal(RevertError):
    def __init__(self, path: str, expected: bytes | None, current: bytes | None) -> None:
        super().__init__(STALE_MESSAGE)
        self.path = path
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class ApproveResult:
    change: Change
    path: str
    etag: str | None


def _pending(change_id: int) -> Change:
    c = changes_log.get(change_id)
    if c is None:
        raise ChangeNotFound(f"no change #{change_id}")
    if c.status != "pending":
        raise NotApprovable(f"change #{change_id} is {c.status}")
    return c


def _bytes(blob: str | None) -> bytes | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob)
    except history.BlobNotFound:
        raise VersionGone("this version is no longer available") from None


def _write_approved(c: Change, flip: Flip, target: bytes | None, current: bytes | None) -> WriteResult:
    reason = c.reason or f"approved change #{c.id}"
    if target is None:  # a delete
        if current is None:  # already gone (forced): the outcome holds
            changes_log.apply_pending(c.id, before_blob=c.before_blob, after_blob=None)
            return WriteResult("applied", str(c.id), None, flip.at, None)
        return vault_write.write(
            flip.at, op="delete", actor=c.actor, reason=reason,
            base_etag=compute_etag(current), approved_change=c.id,
        )
    try:
        text = target.decode("utf-8")
    except UnicodeDecodeError:
        raise NotApprovable("the proposed version is not UTF-8 text") from None
    if current is None:
        # A forced worker edit/move of a vanished note would be a worker
        # create, which the log never records: nothing to approve into.
        if not vault_write.records_change(c.actor, "create"):
            raise NotApprovable("the note no longer exists; reject this change")
        return vault_write.write(
            flip.to, content=text, op="create", actor=c.actor, reason=reason,
            verbatim=True, approved_change=c.id,
        )
    if current == target and flip.at == flip.to:  # already on disk (forced)
        before = history.put_blob(current)
        changes_log.apply_pending(c.id, before_blob=before, after_blob=before)
        return WriteResult("applied", str(c.id), compute_etag(current), flip.at, None)
    base = compute_etag(current)
    if flip.at != flip.to:
        return vault_write.write(
            flip.at, op="move", dest=flip.to, content=text, actor=c.actor, reason=reason,
            base_etag=base, verbatim=True, approved_change=c.id,
        )
    return vault_write.write(
        flip.at, content=text, actor=c.actor, reason=reason, base_etag=base,
        verbatim=True, approved_change=c.id,
    )


def approve(change_id: int, *, force: bool = False) -> ApproveResult:
    # Shares revert's lock: an approval and a revert never interleave on a row.
    with _rv._lock:
        c = _pending(change_id)
        flip = _rv.held_flip(c)
        target = _bytes(flip.target)  # fail before any write when it was collected
        current = _rv.read_current(flip.at)
        if not _rv.matches_blob(current, flip.expect) and not force:
            try:
                expected = _bytes(flip.expect)
            except VersionGone:
                expected = None
            raise StaleProposal(flip.at, expected, current)
        res = _write_approved(c, flip, target, current)
        c = changes_log.get(c.id) or c
    log.info("approved change #%s by %s on %s", c.id, c.actor, res.path)
    return ApproveResult(c, res.path, res.etag)


def reject(change_id: int) -> Change:
    with _rv._lock:
        c = _pending(change_id)
        if not changes_log.set_status(c.id, "rejected", expect=("pending",)):
            raise NotApprovable(f"change #{change_id} is no longer pending")
        return changes_log.get(c.id) or c
