from ghostbrain.api.repo import projects
from ghostbrain.ontology import identity
from ghostbrain.ontology.schema import SELF_UID
from ghostbrain.ontology.store import Store


def test_create_project_assigns_uuid(tmp_vault):
    p = projects.create_project("work", "Orbit")
    assert len(p["uuid"]) == 32


def test_ensure_project_uuids_backfills_and_is_stable(tmp_vault):
    p = projects.create_project("work", "Orbit")
    items = projects._read()
    items[0].pop("uuid")
    projects._write(items)
    first = projects.ensure_project_uuids()
    second = projects.ensure_project_uuids()
    assert first[0]["uuid"] == second[0]["uuid"]
    assert projects.get_project_by_uuid(first[0]["uuid"])["id"] == p["id"]


def test_rename_keeps_uuid(tmp_vault):
    p = projects.create_project("work", "Orbit")
    projects.rename_project("work", p["slug"], name="Orbit Programme")
    renamed = projects.get_project_by_uuid(p["uuid"])
    assert renamed is not None and renamed["name"] == "Orbit Programme"


def test_seed_payload_has_self_contexts_projects(tmp_vault, tmp_path):
    store = Store(tmp_path / "o.db")
    p = projects.create_project("work", "Orbit")
    payload = identity.seed_payload(store)
    uids = {n["uid"]: n for n in payload["nodes"]}
    assert uids[SELF_UID]["kind"] == "Self"
    work = identity.context_uuid(store, "work")
    assert uids[work]["kind"] == "Context" and uids[work]["props"]["name"] == "work"
    assert uids[p["uuid"]]["kind"] == "Project"
    assert {"type": "IN", "src": p["uuid"], "dst": work, "props": {}} in payload["edges"]
    assert {"type": "WORKS_IN", "src": SELF_UID, "dst": work, "props": {}} in payload["edges"]
    # stable across calls
    assert identity.seed_payload(store) == payload
