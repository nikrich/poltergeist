"""Content-hash etags over raw file bytes (spec B §1 step 2)."""
from __future__ import annotations

import hashlib

ETAG_LEN = 16


def compute_etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ETAG_LEN]


def normalize_if_match(value: str | None) -> str | None:
    """Accept ``"abc"``, ``W/"abc"`` or bare ``abc``. ``*`` / empty mean "no
    precondition" (the op's own existence rules still apply)."""
    if value is None:
        return None
    v = value.strip()
    if v.startswith("W/"):
        v = v[2:].strip()
    v = v.strip('"').strip()
    if not v or v == "*":
        return None
    return v
