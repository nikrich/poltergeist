"""Exceptions raised by the vault write path. ``ghostbrain.api.vault_http``
maps them to HTTP statuses (400 / 404 / 409 / 422 / 428)."""
from __future__ import annotations

CONFLICT_MESSAGE = "note changed since you read it — re-read and retry"


class VaultWriteError(Exception):
    """Base class for every vault-write failure."""


class InvalidPath(VaultWriteError, ValueError):
    """Vault-relative path is absolute, traverses, escapes the root, or has a
    suffix the write path does not handle."""


class FileMissing(VaultWriteError):
    """modify / delete / move targeted a file that does not exist."""


class MalformedNote(VaultWriteError):
    """The file is not UTF-8, or a field edit hit frontmatter that is not a
    YAML mapping."""


class WriteConflict(VaultWriteError):
    """The file changed since the caller read it (etag mismatch), or a create
    / move destination already exists."""

    def __init__(self, current_etag: str | None, message: str = CONFLICT_MESSAGE) -> None:
        super().__init__(message)
        self.current_etag = current_etag


ETAG_REQUIRED_MESSAGE = "read the note first and send its etag (If-Match) to change it"


class EtagRequired(VaultWriteError):
    """A non-user writer changed an existing file without ``base_etag`` and
    the file is not exactly what that writer last wrote there (spec B §1:
    required for actor != worker when op != create). HTTP 428."""

    def __init__(self, current_etag: str | None) -> None:
        super().__init__(ETAG_REQUIRED_MESSAGE)
        self.current_etag = current_etag
