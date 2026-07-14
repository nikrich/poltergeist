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
from pathlib import Path

import yaml

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.routing_config")

# Fallback for vaults without a `contexts:` key. Do not add call sites — use
# contexts() instead.
LEGACY_CONTEXTS: tuple[str, ...] = ("sanlam", "codeship", "reducedrecipes", "personal")

# Seeded into brand-new vaults by bootstrap.
DEFAULT_CONTEXTS: tuple[str, ...] = ("personal", "work")

_warned = False


def contexts(root: Path | None = None) -> tuple[str, ...]:
    """Configured context list from routing.yaml, or the legacy fallback.

    ``needs_review`` is never part of this list: callers that want it (the
    router enum, digest ordering) append it themselves.
    """
    global _warned
    f = (root or vault_path()) / "90-meta" / "routing.yaml"
    raw: dict = {}
    try:
        loaded = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — malformed YAML must not kill callers
        log.warning("could not read %s: %s", f, e)

    value = raw.get("contexts")
    if (
        isinstance(value, list)
        and value
        and all(isinstance(c, str) and c.strip() for c in value)
    ):
        return tuple(c.strip() for c in value)

    if not _warned:
        log.warning(
            "no valid `contexts:` list in %s — falling back to legacy contexts %s. "
            "Add a `contexts:` key (or run ghostbrain-bootstrap) to configure.",
            f,
            LEGACY_CONTEXTS,
        )
        _warned = True
    return LEGACY_CONTEXTS
