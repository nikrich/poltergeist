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
    WRITABLE_SUFFIXES,
    NoteSnapshot,
    Op,
    WriteResult,
    current_etag,
    read,
    resolve_safe,
    write,
    write_new,
)

__all__ = [
    "ASSISTANT", "DELETE_FIELD", "MCP", "RESTORE", "USER", "WRITABLE_SUFFIXES",
    "Actor", "FileMissing", "HistoryUnavailable", "InvalidPath", "MalformedNote",
    "NoteSnapshot", "Op", "ParsedNote", "VaultWriteError", "WriteConflict", "WriteResult",
    "apply_fields", "compute_etag", "current_etag", "find_key_block", "lines_of",
    "load_metadata", "normalize_if_match", "parse_actor", "parse_note", "plugin_actor",
    "read", "resolve_safe", "splice_body", "worker_actor", "write", "write_new",
]
