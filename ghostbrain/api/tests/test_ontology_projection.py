import pytest

pytest.importorskip("arcadedb_embedded")

import frontmatter  # noqa: E402

from ghostbrain.api.repo import projects  # noqa: E402
from ghostbrain.ontology import backlog, projection_md, service as service_mod, triage  # noqa: E402
from ghostbrain.ontology.extract import CandidateIn  # noqa: E402


class FakeEmbedder:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _ratified(svc, p, statement="Today lapse is day 31."):
    svc.store.upsert_binding(p["uuid"], "a1", "20-contexts/work/a1.md", "A1", "bound")
    svc.commit("bind", {"project": p["uuid"], "artefacts": [
        {"aid": "a1", "path": "20-contexts/work/a1.md", "title": "A1"}]})
    c = CandidateIn(kind="Rule", name="lapse day", statement=statement, value="31",
                    existing_uid=None, quote="day 31", locator="", confidence=0.7)
    triage.triage(svc.store, p["uuid"], "a1", c, FakeEmbedder())
    item = svc.store.open_items(p["uuid"])[-1]["id"]
    backlog.act(svc, item, "ratify")
    return svc.store.events()[-1].payload["node"]["uid"]


def test_ratify_writes_generated_note_with_evidence(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    uid = _ratified(svc, p)
    files = list((tmp_vault / "20-contexts/work/projects/orbit/ontology/rule").glob("*.md"))
    assert len(files) == 1 and files[0].name.startswith(uid[:8])
    post = frontmatter.load(files[0])
    assert post["type"] == "ontology" and post["uuid"] == uid and post["generated"] is True
    assert "[[20-contexts/work/a1]]" in post.content and "day 31" in post.content


def test_revert_removes_generated_note(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    uid = _ratified(svc, p)
    svc.commit("revert", {"uid": uid, "project": p["uuid"]})
    assert list((tmp_vault / "20-contexts/work/projects/orbit/ontology").rglob("*.md")) == []


def test_project_rename_moves_projection(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    uid = _ratified(svc, p)
    projects.rename_project("work", p["slug"], name="Orbit Programme")
    renamed = projects.get_project_by_uuid(p["uuid"])
    assert renamed["slug"] != p["slug"]
    old_dir = tmp_vault / f"20-contexts/work/projects/{p['slug']}/ontology"
    assert not old_dir.exists() or list(old_dir.rglob("*.md")) == []
    new_dir = tmp_vault / f"20-contexts/work/projects/{renamed['slug']}/ontology"
    for f in new_dir.rglob("*.md"):
        f.unlink()
    with svc.graph_session() as g:
        assert projection_md.write_project(g, p["uuid"]) == 1
    files = list(new_dir.rglob("*.md"))
    assert len(files) == 1 and files[0].name.startswith(uid[:8])
    assert not old_dir.exists() or list(old_dir.rglob("*.md")) == []


def test_identical_rewrite_leaves_mtime_unchanged(ontology_root, tmp_vault):
    import os
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    _ratified(svc, p)
    [f] = (tmp_vault / "20-contexts/work/projects/orbit/ontology/rule").glob("*.md")
    os.utime(f, ns=(1_000_000_000, 1_000_000_000))
    with svc.graph_session() as g:
        assert projection_md.write_project(g, p["uuid"]) == 1
    assert f.stat().st_mtime_ns == 1_000_000_000
