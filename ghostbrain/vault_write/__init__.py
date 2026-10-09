"""The single vault write path (spec 2026-10-09-ai-changes-revert-design.md, slice B1)."""
from ghostbrain.vault_write.errors import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    VaultWriteError,
    WriteConflict,
)
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

__all__ = [
    "DELETE_FIELD",
    "FileMissing",
    "InvalidPath",
    "MalformedNote",
    "ParsedNote",
    "VaultWriteError",
    "WriteConflict",
    "apply_fields",
    "find_key_block",
    "lines_of",
    "load_metadata",
    "parse_note",
    "splice_body",
]
