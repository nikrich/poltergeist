"""The single vault write path (spec 2026-10-09-ai-changes-revert-design.md, slice B1)."""
from ghostbrain.history.store import HistoryUnavailable
from ghostbrain.vault_write.actor import (
    ASSISTANT,
    MCP,
    RESTORE,
    USER,
    Actor,
    parse_actor,
    plugin_actor,
    worker_actor,
)
from ghostbrain.vault_write.errors import (
    EtagRequired,
    FileMissing,
    InvalidPath,
    MalformedNote,
    VaultWriteError,
    WriteConflict,
)
from ghostbrain.vault_write.etag import compute_etag, normalize_if_match
from ghostbrain.vault_write.text import (
    DELETE_FIELD,
    ParsedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)
from ghostbrain.vault_write.writer import (
    UNLISTED_ACTORS,
    WRITABLE_SUFFIXES,
    HoldPolicy,
    NoteSnapshot,
    Op,
    ProposedChange,
    WriteResult,
    current_etag,
    needs_base_etag,
    read,
    records_change,
    resolve_safe,
    set_hold_policy,
    write,
    write_new,
)
from ghostbrain.vault_write import risk  # noqa: E402  (imports writer; must come after it)

__all__ = [
    "ASSISTANT", "DELETE_FIELD", "MCP", "RESTORE", "USER", "UNLISTED_ACTORS", "WRITABLE_SUFFIXES",
    "Actor", "EtagRequired", "FileMissing", "HistoryUnavailable", "HoldPolicy",
    "InvalidPath", "MalformedNote", "NoteSnapshot", "Op", "ParsedNote", "ProposedChange",
    "VaultWriteError", "WriteConflict", "WriteResult",
    "apply_fields", "compute_etag", "current_etag", "find_key_block", "lines_of",
    "load_metadata", "needs_base_etag", "normalize_if_match", "parse_actor", "parse_note",
    "plugin_actor", "read", "records_change", "resolve_safe", "risk", "set_hold_policy",
    "splice_body", "worker_actor", "write", "write_new",
]
