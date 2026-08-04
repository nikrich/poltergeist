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

# Seeded into brand-new vaults by bootstrap, and the fallback whenever
# routing.yaml has no valid `contexts:` list. Run `ghostbrain-bootstrap`
# (or `ghostbrain-api bootstrap`) once to persist a vault's real list.
DEFAULT_CONTEXTS: tuple[str, ...] = ("personal", "work")

_warned = False


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
