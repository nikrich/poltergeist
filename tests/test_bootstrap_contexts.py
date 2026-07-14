"""bootstrap(): context folders and seeds come from configuration.

Fresh vault → neutral DEFAULT_CONTEXTS. Existing vault → whatever
routing_config resolves (configured or legacy fallback), and routing.yaml
gains the `contexts:` key by APPEND (user edits/comments preserved).
"""
from __future__ import annotations

import yaml

from ghostbrain import routing_config
from ghostbrain.bootstrap import bootstrap


def test_fresh_vault_seeds_default_contexts(vault):
    root = bootstrap()
    for ctx in routing_config.DEFAULT_CONTEXTS:
        assert (root / "20-contexts" / ctx / "_index.md").exists()
    routing = yaml.safe_load((root / "90-meta" / "routing.yaml").read_text())
    assert routing["contexts"] == list(routing_config.DEFAULT_CONTEXTS)


def test_fresh_vault_has_no_legacy_context_folders(vault):
    root = bootstrap()
    assert not (root / "20-contexts" / "sanlam").exists()


def test_seeded_files_do_not_mention_legacy_contexts(vault):
    root = bootstrap()
    for f in root.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".yaml"):
            body = f.read_text(encoding="utf-8")
            for name in ("sanlam", "codeship", "reducedrecipes"):
                assert name not in body, f"{name} leaked into seed {f}"


def test_router_prompt_seed_uses_contexts_placeholder(vault):
    root = bootstrap()
    prompt = (root / "90-meta" / "prompts" / "router.md").read_text()
    assert "{{contexts}}" in prompt


def test_existing_vault_without_key_gets_contexts_appended(vault):
    root = bootstrap()  # first boot: default contexts
    routing_file = root / "90-meta" / "routing.yaml"
    # Simulate a legacy vault: strip the contexts key, keep a user comment.
    body = routing_file.read_text()
    stripped = "\n".join(
        line for line in body.splitlines()
        if not line.startswith("contexts:") and not line.startswith("  - ")
    )
    routing_file.write_text("# user comment to preserve\n" + stripped + "\n")

    bootstrap()

    after = routing_file.read_text()
    assert "# user comment to preserve" in after
    routing = yaml.safe_load(after)
    # Key absent → legacy fallback list is what gets recorded.
    assert routing["contexts"] == list(routing_config.LEGACY_CONTEXTS)


def test_existing_vault_with_key_is_untouched(vault):
    root = bootstrap()
    routing_file = root / "90-meta" / "routing.yaml"
    routing_file.write_text("contexts:\n  - alpha\n")

    bootstrap()

    assert routing_file.read_text() == "contexts:\n  - alpha\n"
    assert (root / "20-contexts" / "alpha" / "_index.md").exists()


def test_bootstrap_is_idempotent(vault):
    a = bootstrap()
    before = sorted(str(p.relative_to(a)) for p in a.rglob("*"))
    b = bootstrap()
    after = sorted(str(p.relative_to(b)) for p in b.rglob("*"))
    assert a == b
    assert before == after
