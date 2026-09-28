from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from ghostbrain import routing_config as rc

COMMENTED = """\
# Routing rules — hand edited
version: 1

# The vault's contexts.
contexts:
  - personal
  - work

# GitHub orgs → context.
github:
  orgs:
    acme: work   # keep this comment
gmail:
  sender_domains:
    acme.com: work
"""


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(COMMENTED, encoding="utf-8")
    return root


def _text(root: Path) -> str:
    return (root / "90-meta" / "routing.yaml").read_text(encoding="utf-8")


def test_add_context_preserves_everything_else(v):
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")
    text = _text(v)
    assert "contexts:\n  - personal\n  - work\n  - agencyx\n" in text
    before, after = COMMENTED.split("contexts:")[0], COMMENTED.split("# GitHub orgs")[1]
    assert text.startswith(before)
    assert text.endswith(after)
    assert "acme: work   # keep this comment" in text
    assert rc.contexts(v) == ("personal", "work", "agencyx")


def test_add_creates_context_folders(v):
    rc.add_context("agencyx", v)
    ctx = v / "20-contexts" / "agencyx"
    assert (ctx / "_index.md").exists() and (ctx / "_profile.md").exists()


def test_archive_and_restore(v):
    rc.add_context("agencyx", v)
    assert rc.archive_context("agencyx", v) == ("personal", "work")
    assert rc.archived_contexts(v) == ("agencyx",)
    assert "archived_contexts:\n  - agencyx\n" in _text(v)
    assert (v / "20-contexts" / "agencyx").exists()          # nothing deleted
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")  # restore
    assert rc.archived_contexts(v) == ()


@pytest.mark.parametrize("name", ["", "Agency X", "needs_review", "-x", "a" * 41, "x/y", "../up"])
def test_invalid_names_rejected(v, name):
    with pytest.raises(rc.ContextError):
        rc.add_context(name, v)
    assert _text(v) == COMMENTED


def test_duplicate_and_last_and_unknown(v):
    with pytest.raises(rc.ContextError):
        rc.add_context("work", v)
    rc.archive_context("work", v)
    with pytest.raises(rc.ContextError):
        rc.archive_context("personal", v)                    # last active
    with pytest.raises(rc.ContextError):
        rc.archive_context("nope", v)


def test_flow_style_contexts_rewritten(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, work]\ngithub:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    data = yaml.safe_load(_text(root))
    assert data["contexts"] == ["personal", "work", "agencyx"]
    assert data["github"] == {"orgs": {}}


def test_missing_contexts_key_uses_defaults_then_writes(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("github:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    assert rc.contexts(root) == (*rc.DEFAULT_CONTEXTS, "agencyx")


# --- fix round 1: CRLF preservation ------------------------------------


def test_crlf_preserved(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    crlf_text = COMMENTED.replace("\n", "\r\n")
    routing_file = root / "90-meta" / "routing.yaml"
    routing_file.write_bytes(crlf_text.encode("utf-8"))

    rc.add_context("agencyx", root)

    raw = routing_file.read_bytes()
    before = COMMENTED.split("contexts:")[0].replace("\n", "\r\n").encode("utf-8")
    after = COMMENTED.split("# GitHub orgs")[1].replace("\n", "\r\n").encode("utf-8")
    assert raw.startswith(before)
    assert raw.endswith(after)
    assert b"contexts:\r\n  - personal\r\n  - work\r\n  - agencyx\r\n" in raw
    # No bare LF anywhere — every newline in the file is part of a CRLF pair.
    assert raw.replace(b"\r\n", b"").find(b"\n") == -1
    assert yaml.safe_load(raw.decode("utf-8"))["contexts"] == ["personal", "work", "agencyx"]


# --- fix round 1: comment preservation ----------------------------------


def test_block_comment_line_preserved_on_add(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    text = (
        "contexts:\n"
        "  - personal\n"
        "  - work\n"
        "  # keep this note\n"
        "github:\n"
        "  orgs: {}\n"
    )
    (root / "90-meta" / "routing.yaml").write_text(text, encoding="utf-8")

    rc.add_context("agencyx", root)

    out = _text(root)
    assert "contexts:\n  - personal\n  - work\n  - agencyx\n  # keep this note\n" in out
    data = yaml.safe_load(out)
    assert data["contexts"] == ["personal", "work", "agencyx"]
    assert data["github"] == {"orgs": {}}


def test_key_line_trailing_comment_preserved_on_add(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    text = "contexts:  # workspaces\n  - personal\n  - work\ngithub:\n  orgs: {}\n"
    (root / "90-meta" / "routing.yaml").write_text(text, encoding="utf-8")

    rc.add_context("agencyx", root)

    out = _text(root)
    assert "contexts:  # workspaces\n  - personal\n  - work\n  - agencyx\n" in out
    data = yaml.safe_load(out)
    assert data["contexts"] == ["personal", "work", "agencyx"]


def test_comments_preserved_through_archive(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    text = (
        "contexts:  # workspaces\n"
        "  - personal\n"
        "  - work\n"
        "  # keep this note\n"
        "github:\n"
        "  orgs: {}\n"
    )
    (root / "90-meta" / "routing.yaml").write_text(text, encoding="utf-8")

    rc.archive_context("work", root)

    out = _text(root)
    assert "contexts:  # workspaces\n  - personal\n  # keep this note\n" in out
    data = yaml.safe_load(out)
    assert data["contexts"] == ["personal"]
    assert data["archived_contexts"] == ["work"]
    assert data["github"] == {"orgs": {}}


# --- fix round 1: concurrency -------------------------------------------


def test_concurrent_add_context_all_present(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - personal\n  - work\n", encoding="utf-8"
    )
    names = [f"agency{i}" for i in range(10)]
    threads = [threading.Thread(target=rc.add_context, args=(n, root)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    active = rc.contexts(root)
    assert len(active) == len(set(active)) == 12
    for n in names:
        assert n in active


# --- final review fixes --------------------------------------------------


def test_archive_restore_cycles_do_not_grow_file(v):
    rc.add_context("agencyx", v)
    after_add = _text(v)
    for _ in range(3):
        rc.archive_context("agencyx", v)
        rc.add_context("agencyx", v)
    assert _text(v) == after_add


@pytest.mark.parametrize("name", ["yes", "off", "no", "2024", "0x1f", "2024-01-01", "017", "null", "true"])
def test_names_yaml_reads_as_non_string_rejected(v, name):
    with pytest.raises(rc.ContextError, match="would be read as a number/boolean/date"):
        rc.add_context(name, v)
    assert _text(v) == COMMENTED


def test_unusual_layout_logs_warning_with_path(tmp_path, caplog):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    # Two `contexts:` keys: the block writer rewrites the first, YAML loads
    # the last — verification fails.
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - personal\n  - work\nsecret: hunter2\ncontexts:\n  - personal\n  - work\n",
        encoding="utf-8",
    )
    with (
        caplog.at_level("WARNING", logger="ghostbrain.routing_config"),
        pytest.raises(rc.ContextError, match="unusual contexts layout"),
    ):
        rc.add_context("agencyx", root)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("routing.yaml" in m and "unusual" in m for m in msgs)
    assert not any("hunter2" in m for m in msgs)


def test_restore_legacy_archived_name_not_matching_regex(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - personal\narchived_contexts:\n  - Agency_X\n", encoding="utf-8"
    )
    assert rc.add_context("Agency_X", root) == ("personal", "Agency_X")
    assert rc.archived_contexts(root) == ()
    # A brand-new name with the same shape is still rejected.
    with pytest.raises(rc.ContextError):
        rc.add_context("Other_Y", root)


def test_routing_write_lock_shared_with_merge_routing(tmp_path, monkeypatch):
    from ghostbrain.api.repo import routing as repo_routing

    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("contexts:\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(root))

    done = threading.Event()

    def _merge():
        repo_routing.merge_routing({"joplin": {"host": "h"}})
        done.set()

    with rc.routing_write_lock():
        t = threading.Thread(target=_merge)
        t.start()
        assert not done.wait(0.3)       # blocked while the context writer holds the lock
    assert done.wait(5)
    t.join()
    assert yaml.safe_load(_text(root))["joplin"] == {"host": "h"}

    done.clear()

    def _remove():
        repo_routing.remove_routing_path("joplin.host")
        done.set()

    with rc.routing_write_lock():
        t = threading.Thread(target=_remove)
        t.start()
        assert not done.wait(0.3)
    assert done.wait(5)
    t.join()
