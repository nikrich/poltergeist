import pytest

from ghostbrain.ontology import service as service_mod
from ghostbrain.ontology.graph import GoldGraph, GraphLocked


def test_status_reports_lock_without_raising(ontology_root, monkeypatch):
    def locked(self):
        raise GraphLocked("the gold graph is locked by another process (x)")
    monkeypatch.setattr(GoldGraph, "open", locked)
    svc = service_mod.get_service()
    st = svc.status()
    assert st == {"available": False, "reason": "the gold graph is locked by another process (x)"}


def test_commit_appends_even_when_graph_unavailable(ontology_root, monkeypatch):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked")))
    svc = service_mod.get_service()
    seq = svc.commit("relabel", {"uid": "x", "name": "y"})
    assert svc.store.head() == seq


def test_non_ontology_routes_unaffected_by_locked_graph(ontology_root, monkeypatch, client, auth_headers):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked")))
    service_mod.get_service().status()
    assert client.get("/v1/projects", headers=auth_headers).status_code == 200


def test_seed_then_graph_has_core_layer(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.api.repo import projects  # noqa: PLC0415
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    with svc.graph_session() as g:
        assert g.node(p["uuid"])["kind"] == "Project"
        assert g.node("self")["kind"] == "Self"


def test_catch_up_after_reopen(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    svc.seed()
    service_mod.reset_service()          # graph closed; log keeps going
    svc2 = service_mod.get_service()
    svc2.store.append_event("relabel", {"uid": "self", "name": "me-renamed"})
    with svc2.graph_session() as g:      # opening catches up
        assert g.node("self")["name"] == "me-renamed"


def test_on_applied_hook_receives_projects(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    seen: list[list[str]] = []
    svc.on_applied.append(lambda s, projects: seen.append(projects))
    svc.commit("bind", {"project": "p9", "artefacts": []})
    assert seen and "p9" in seen[-1]


def test_projection_failure_never_loses_the_commit(ontology_root, tmp_vault, monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import projector  # noqa: PLC0415
    svc = service_mod.get_service()
    real = projector.catch_up

    def boom(store, graph):
        raise RuntimeError("projector exploded")
    monkeypatch.setattr(projector, "catch_up", boom)
    seq = svc.commit("relabel", {"uid": "self", "name": "a"})
    assert svc.store.head() == seq
    assert svc._graph is None
    monkeypatch.setattr(projector, "catch_up", real)
    svc.seed()
    svc.store.append_event("relabel", {"uid": "self", "name": "b"})
    with svc.graph_session() as g:
        assert g.node("self")["name"] == "b"


def test_raising_hook_does_not_fail_commit(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()

    def bad(s, projects):
        raise RuntimeError("hook")
    svc.on_applied.append(bad)
    seq = svc.commit("bind", {"project": "p1", "artefacts": []})
    assert svc.store.head() == seq


def test_notify_is_incremental_when_graph_open(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    svc.commit("bind", {"project": "p1", "artefacts": []})
    seen: list[list[str]] = []
    svc.on_applied.append(lambda s, projects: seen.append(projects))
    svc.commit("bind", {"project": "p2", "artefacts": []})
    assert seen == [["p2"]]


def test_notify_covers_open_time_catch_up_only_for_unapplied(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    svc.commit("bind", {"project": "p1", "artefacts": []})
    service_mod.reset_service()
    svc2 = service_mod.get_service()
    svc2.store.append_event("bind", {"project": "p2", "artefacts": []})
    seen: list[list[str]] = []
    svc2.on_applied.append(lambda s, projects: seen.append(projects))
    svc2.commit("bind", {"project": "p3", "artefacts": []})
    assert seen == [["p2", "p3"]]


def test_rebuild_smoke(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    svc.seed()
    svc.commit("relabel", {"uid": "self", "name": "z"})
    assert svc.rebuild() >= 2
    with svc.graph_session() as g:
        assert g.node("self")["name"] == "z"
