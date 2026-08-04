"""Digest ordering and anticipation iterate configured contexts."""
from __future__ import annotations

from ghostbrain.metrics import anticipation as anticipation_mod
from ghostbrain.worker import digest as digest_mod
from ghostbrain.worker import weekly_digest as weekly_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_daily_ordering_uses_configured_then_alpha_extras(vault):
    _configure(vault, ["beta", "alpha"])
    ordered = digest_mod._ordered_contexts(
        {"alpha": [], "beta": [], "zzz": [], "needs_review": []}
    )
    assert ordered == ["beta", "alpha", "needs_review", "zzz"]


def test_weekly_quiet_contexts_use_configured_list(vault):
    _configure(vault, ["alpha", "beta"])
    quiet = weekly_mod._quiet_contexts({"alpha": 10, "needs_review": 0})
    assert quiet == ["beta"]  # beta has 0 events; needs_review never counts


def test_weekly_ordering_uses_configured_list(vault):
    _configure(vault, ["beta", "alpha"])
    ordered = weekly_mod._ordered_contexts({"alpha": 1, "beta": 2, "zzz": 3})
    assert ordered == ["beta", "alpha", "zzz"]


def test_anticipation_only_considers_configured_contexts(vault):
    _configure(vault, ["alpha"])
    # No audit data at all → no anticipations, but critically no crash and
    # no iteration over legacy contexts.
    assert anticipation_mod.detect_anticipations() == []
