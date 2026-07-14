"""routing_config.contexts(): the single source of truth for the context list.

routing.yaml's `contexts:` key drives the router enum, notes-API validation,
digests, and metrics. Missing/invalid values fall back to the legacy four so
pre-existing vaults keep working untouched.
"""
from __future__ import annotations

from pathlib import Path

from ghostbrain import routing_config


def _write_routing(vault: Path, body: str) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def test_configured_contexts_are_returned_in_order(vault):
    _write_routing(vault, "version: 1\ncontexts:\n  - alpha\n  - beta\n")
    assert routing_config.contexts() == ("alpha", "beta")


def test_missing_key_falls_back_to_legacy(vault):
    _write_routing(vault, "version: 1\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_missing_file_falls_back_to_legacy(vault):
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_empty_list_falls_back_to_legacy(vault):
    _write_routing(vault, "contexts: []\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_non_list_falls_back_to_legacy(vault):
    _write_routing(vault, "contexts: banana\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_non_string_entries_fall_back_to_legacy(vault):
    _write_routing(vault, "contexts:\n  - alpha\n  - 42\n")
    assert routing_config.contexts() == routing_config.LEGACY_CONTEXTS


def test_entries_are_stripped(vault):
    _write_routing(vault, 'contexts:\n  - " alpha "\n  - beta\n')
    assert routing_config.contexts() == ("alpha", "beta")


def test_explicit_root_overrides_vault_path(vault, tmp_path):
    other = tmp_path / "other-vault"
    _write_routing(other, "contexts:\n  - solo\n")
    assert routing_config.contexts(root=other) == ("solo",)


def test_default_contexts_are_neutral():
    assert routing_config.DEFAULT_CONTEXTS == ("personal", "work")
