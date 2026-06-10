"""move_jot/list_jots/write_inbox_jot with projects."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.notes_manual import (
    list_jots,
    move_jot,
    write_inbox_jot,
)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "00-inbox/raw/manual").mkdir(parents=True)
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_move_jot_into_project_folder_and_frontmatter(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("ship the chat feature")
    moved = move_jot(
        jot["id"], to_context="codeship", to_project="poltergeist",
        confidence=0.9, method="llm", reasoning="r",
    )
    assert moved["context"] == "codeship"
    assert moved["project"] == "poltergeist"
    assert moved["path"].startswith("20-contexts/codeship/projects/poltergeist/")
    post = frontmatter.load(vault / moved["path"])
    assert post["project"] == "poltergeist"


def test_move_jot_without_project_unchanged(vault: Path):
    jot = write_inbox_jot("plain note")
    moved = move_jot(
        jot["id"], to_context="personal",
        confidence=1.0, method="user", reasoning="r",
    )
    assert moved["path"].startswith("20-contexts/personal/notes/")
    assert moved.get("project") is None


def test_reroute_out_of_project_clears_frontmatter(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("note")
    move_jot(jot["id"], to_context="codeship", to_project="poltergeist",
             confidence=0.9, method="llm", reasoning="r")
    moved = move_jot(jot["id"], to_context="codeship",
                     confidence=1.0, method="user", reasoning="r")
    assert moved["path"].startswith("20-contexts/codeship/notes/")
    post = frontmatter.load(vault / moved["path"])
    assert post.get("project") is None


def test_list_jots_scans_project_folders_and_filters(vault: Path):
    projects.create_project("codeship", "Poltergeist")
    a = write_inbox_jot("in project")
    move_jot(a["id"], to_context="codeship", to_project="poltergeist",
             confidence=0.9, method="llm", reasoning="r")
    b = write_inbox_jot("loose note")
    move_jot(b["id"], to_context="codeship",
             confidence=1.0, method="user", reasoning="r")
    page = list_jots()
    by_id = {i["id"]: i for i in page["items"]}
    assert by_id[a["id"]]["project"] == "poltergeist"
    assert by_id[b["id"]]["project"] is None
    only = list_jots(project="poltergeist")
    assert [i["id"] for i in only["items"]] == [a["id"]]


def test_write_inbox_jot_extra_frontmatter(vault: Path):
    jot = write_inbox_jot("summary body", extra={"source": "chat-summary", "chat_id": "c1"})
    post = frontmatter.load(vault / jot["path"])
    assert post["source"] == "chat-summary"
    assert post["chat_id"] == "c1"


def test_move_jot_project_branch_rejects_traversal_context(vault: Path, tmp_path: Path):
    jot = write_inbox_jot("stay put")
    with pytest.raises(ValueError):
        move_jot(jot["id"], to_context="../../outside", to_project="x",
                 confidence=1.0, method="user", reasoning="evil")
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path.parent / "outside").exists()
    # file untouched in the inbox
    assert (vault / "00-inbox/raw/manual" / f"{jot['id']}.md").exists()


def test_route_jot_core_passes_project(vault, monkeypatch):
    import ghostbrain.api.repo.notes_manual as nm
    from ghostbrain.worker.router import RoutingDecision

    projects.create_project("codeship", "Poltergeist")
    jot = write_inbox_jot("note about the brain")
    monkeypatch.setattr(
        nm, "route_event",
        lambda event, **kw: RoutingDecision(
            context="codeship", confidence=0.9, reasoning="r",
            method="llm", project="poltergeist",
        ),
    )
    from ghostbrain.api.repo.notes_manual import route_existing_jot
    result = route_existing_jot(jot["id"])
    assert result["routingStatus"] == "routed"
    assert result["context"] == "codeship"
    assert result["project"] == "poltergeist"
    assert result["path"].startswith("20-contexts/codeship/projects/poltergeist/")
