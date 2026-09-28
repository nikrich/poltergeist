"""Vault-level routing configuration accessors.

The context *list* lives in routing.yaml under a top-level ``contexts:`` key.
This module is the single source of truth for reading it — the router schema,
notes-API validation, digests, and metrics all derive their list from here.

Back-compat: vaults whose routing.yaml predates the key fall back to the
legacy hardcoded four. That tuple may exist NOWHERE else in ghostbrain/
(enforced by tests/test_no_hardcoded_contexts.py).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.routing_config")

# Seeded into brand-new vaults by bootstrap, and the fallback whenever
# routing.yaml has no valid `contexts:` list. Run `ghostbrain-bootstrap`
# (or `ghostbrain-api bootstrap`) once to persist a vault's real list.
DEFAULT_CONTEXTS: tuple[str, ...] = ("personal", "work")

CONTEXT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED_CONTEXTS = frozenset({"needs_review"})

_warned = False

# Serializes the read-modify-write cycle in add_context/archive_context (and
# the internal read+write in _write_context_blocks) so concurrent callers
# can't interleave and lose an update. Reentrant: add_context/archive_context
# hold it across their own call into _write_context_blocks.
_lock = threading.RLock()


class ContextError(ValueError):
    """Invalid, reserved, duplicate, unknown, or last-remaining context."""


def _load(root: Path | None = None) -> dict:
    """Safe-load routing.yaml into a dict; ``{}`` on missing/invalid."""
    r = root or vault_path()
    f = r / "90-meta" / "routing.yaml"
    raw: dict = {}
    try:
        loaded = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — malformed YAML must not kill callers
        log.warning("could not read %s: %s", f, e)
    return raw


def contexts(root: Path | None = None) -> tuple[str, ...]:
    """Configured context list from routing.yaml, or ``DEFAULT_CONTEXTS``.

    routing.yaml's ``contexts:`` key is the single source of truth; when it
    is missing or invalid (including a missing routing.yaml pre-bootstrap)
    we fall back to ``DEFAULT_CONTEXTS`` and warn once. Bootstrap persists
    the in-effect list, so the fallback only fires on never-bootstrapped
    vaults.

    ``needs_review`` is never part of this list: callers that want it (the
    router enum, digest ordering) append it themselves.
    """
    global _warned
    raw = _load(root)
    f = (root or vault_path()) / "90-meta" / "routing.yaml"

    value = raw.get("contexts")
    if (
        isinstance(value, list)
        and value
        and all(isinstance(c, str) and c.strip() for c in value)
    ):
        return tuple(c.strip() for c in value)

    if not _warned:
        log.warning(
            "no valid `contexts:` list in %s — falling back to default "
            "contexts %s. Add a `contexts:` key (or run ghostbrain-bootstrap) "
            "to configure.",
            f,
            DEFAULT_CONTEXTS,
        )
        _warned = True
    return DEFAULT_CONTEXTS


def archived_contexts(root: Path | None = None) -> tuple[str, ...]:
    value = _load(root).get("archived_contexts")
    if isinstance(value, list):
        return tuple(str(c).strip() for c in value if isinstance(c, str) and c.strip())
    return ()


def _block_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """Find the [start, end) line range of the `key:` block, or None."""
    pat = re.compile(rf"^{re.escape(key)}\s*:")
    for i, line in enumerate(lines):
        if pat.match(line):
            end = i + 1
            while end < len(lines):
                nxt = lines[end]
                if nxt.strip() == "" or not (nxt[:1] in (" ", "\t", "-")):
                    break
                end += 1
            return i, end
    return None


def _line_ending(text: str) -> str:
    """The file's own newline style: "\\r\\n" if present anywhere, else "\\n"."""
    return "\r\n" if "\r\n" in text else "\n"


def _key_line_comment(line: str) -> str:
    """The trailing ``  # ...`` comment on a key line, or "" if none."""
    body = line.rstrip("\r\n")
    m = re.search(r"(\s+#.*)$", body)
    return m.group(1) if m else ""


def _comment_lines_in_span(lines: list[str], start: int, end: int) -> list[str]:
    """Comment-only lines (original text, indentation and terminator) in the span."""
    return [line for line in lines[start + 1 : end] if line.strip().startswith("#")]


def _block(
    key: str,
    values: list[str],
    nl: str,
    key_comment: str = "",
    trailing_comment_lines: list[str] | None = None,
) -> str:
    out = f"{key}:{key_comment}{nl}" + "".join(f"  - {v}{nl}" for v in values)
    for line in trailing_comment_lines or ():
        out += line
    return out


def _write_context_blocks(
    root: Path | None, active: list[str], archived: list[str]
) -> None:
    with _lock:
        r = root or vault_path()
        f = r / "90-meta" / "routing.yaml"
        try:
            with open(f, encoding="utf-8", newline="") as fh:
                old_text = fh.read()
        except FileNotFoundError:
            old_text = ""

        old_data = yaml.safe_load(old_text) if old_text.strip() else None
        if not isinstance(old_data, dict):
            old_data = {}

        nl = _line_ending(old_text)
        new_lines = old_text.splitlines(keepends=True)

        for key, values in (("contexts", active), ("archived_contexts", archived)):
            span = _block_span(new_lines, key)
            if not values:
                # Empty list → remove existing block, write nothing new.
                if span is not None:
                    start, end = span
                    new_lines = new_lines[:start] + new_lines[end:]
                continue
            if span is not None:
                start, end = span
                key_comment = _key_line_comment(new_lines[start])
                comment_lines = _comment_lines_in_span(new_lines, start, end)
                block = _block(key, values, nl, key_comment, comment_lines)
                new_lines = new_lines[:start] + [block] + new_lines[end:]
            else:
                block = _block(key, values, nl)
                sep = "" if (not new_lines or new_lines[-1].endswith(nl)) else nl
                new_lines = new_lines + [f"{sep}{nl}{block}" if new_lines else block]

        new_text = "".join(new_lines)

        # Verify: only the contexts/archived_contexts keys may have changed.
        try:
            verify_data = yaml.safe_load(new_text)
        except yaml.YAMLError as e:
            raise ContextError(
                "routing.yaml has an unusual contexts layout; edit it by hand"
            ) from e
        if not isinstance(verify_data, dict):
            raise ContextError(
                "routing.yaml has an unusual contexts layout; edit it by hand"
            )
        if verify_data.get("contexts") != active:
            raise ContextError(
                "routing.yaml has an unusual contexts layout; edit it by hand"
            )
        if archived:
            if verify_data.get("archived_contexts") != archived:
                raise ContextError(
                    "routing.yaml has an unusual contexts layout; edit it by hand"
                )
        elif "archived_contexts" in verify_data:
            raise ContextError(
                "routing.yaml has an unusual contexts layout; edit it by hand"
            )
        other_old = {k: v for k, v in old_data.items() if k not in ("contexts", "archived_contexts")}
        other_new = {k: v for k, v in verify_data.items() if k not in ("contexts", "archived_contexts")}
        if other_old != other_new:
            raise ContextError(
                "routing.yaml has an unusual contexts layout; edit it by hand"
            )

        f.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(f.parent), prefix=".routing.yaml.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
            os.replace(tmp_path, f)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def add_context(name: str, root: Path | None = None) -> tuple[str, ...]:
    name = (name or "").strip()
    if not CONTEXT_NAME_RE.match(name) or name in RESERVED_CONTEXTS:
        raise ContextError(
            "context names use lowercase letters, digits and hyphens (max 40), "
            f"and can't be {sorted(RESERVED_CONTEXTS)}"
        )
    with _lock:
        active = list(contexts(root))
        if name in active:
            raise ContextError(f"context {name!r} already exists")
        archived = [c for c in archived_contexts(root) if c != name]
        active.append(name)
        _write_context_blocks(root, active, archived)
        from ghostbrain.bootstrap import ensure_context_dirs

        ensure_context_dirs(root or vault_path(), name)
        return tuple(active)


def archive_context(name: str, root: Path | None = None) -> tuple[str, ...]:
    with _lock:
        active = list(contexts(root))
        if name not in active:
            raise ContextError(f"unknown context {name!r}")
        if len(active) == 1:
            raise ContextError("at least one context must remain")
        active.remove(name)
        archived = [*archived_contexts(root), name]
        _write_context_blocks(root, active, archived)
        return tuple(active)
