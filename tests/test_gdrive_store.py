from __future__ import annotations

import pytest
import yaml

from ghostbrain.connectors.gdrive import event as ev_mod
from ghostbrain.connectors.gdrive import store
from ghostbrain.connectors.gdrive.convert import ConvertResult
from ghostbrain.paths import vault_path
from ghostbrain.worker import note_generator, pipeline
from ghostbrain.worker.router import RoutingDecision
from tests.gdrive_fakes import drive_file


@pytest.fixture
def fake_pipeline(monkeypatch):
    """process_event stand-in: routes everything to 'work' in live mode."""
    calls = []

    def _process(event):
        calls.append(event)
        note_generator.write_note(
            event, RoutingDecision("work", 0.95, "account", "account"),
            body=event["body"], write_to_context=True,
        )
        return {"context": "work"}

    monkeypatch.setattr(pipeline, "process_event", _process)
    return calls


def _event(fid="F1abc_-Z", name="Roadmap", modified="2026-09-01T10:00:00.000Z",
           body="v1", account="me@x.com"):
    f = drive_file(fid, name, modified=modified, parents=[])
    return ev_mod.build_event(f, account=account, result=ConvertResult(body, False), folder="Work/Plans")


def _front(p):
    text = p.read_text()
    return yaml.safe_load(text.split("---\n")[1]), text.split("---\n", 2)[2]


def test_build_event_shape():
    e = _event()
    assert e["id"] == "gdrive:F1abc_-Z" and e["source"] == "gdrive" and e["type"] == "doc"
    assert e["metadata"]["accountId"] == "me@x.com"
    assert e["metadata"]["driveModifiedTime"] == "2026-09-01T10:00:00.000Z"
    assert e["body"].startswith("# Roadmap\n\n[Open in Drive](https://docs.google.com/d/F1abc_-Z) · Work/Plans\n\nv1")


def test_new_file_goes_through_pipeline_with_stable_name(fake_pipeline):
    assert store.upsert(_event())[0] == "imported"
    paths = store.find_notes("F1abc_-Z")
    assert {p.name for p in paths} == {"roadmap-F1abc_-Z.md"}
    assert len(paths) == 2  # inbox + context twin
    front, _ = _front(paths[0])
    assert front["fileId"] == "F1abc_-Z" and front["folder"] == "Work/Plans"


def test_newer_version_rewrites_in_place_without_pipeline(fake_pipeline, monkeypatch):
    store.upsert(_event())
    fake_pipeline.clear()
    ctx_note = next(p for p in store.find_notes("F1abc_-Z") if "20-contexts" in p.parts)
    text = ctx_note.read_text().replace("routingMethod: account", "routingMethod: account\ntags:\n- keep")
    ctx_note.write_text(text)

    assert store.upsert(_event(modified="2026-09-02T09:00:00.000Z", body="v2"))[0] == "updated"
    assert fake_pipeline == []
    for p in store.find_notes("F1abc_-Z"):
        front, body = _front(p)
        assert front["driveModifiedTime"] == "2026-09-02T09:00:00.000Z"
        assert front["context"] == "work"
        assert body.rstrip().endswith("v2")
    assert _front(ctx_note)[0]["tags"] == ["keep"]


def test_same_version_is_skipped(fake_pipeline):
    store.upsert(_event())
    assert store.upsert(_event())[0] == "skipped"
    assert store.upsert(_event(modified="2026-08-01T00:00:00.000Z"))[0] == "skipped"


def test_upsert_updates_renamed_doc_under_old_filename(fake_pipeline):
    store.upsert(_event(name="Roadmap"))
    assert store.upsert(_event(name="Roadmap 2027", modified="2026-09-03T00:00:00.000Z", body="v3"))[0] == "updated"
    paths = store.find_notes("F1abc_-Z")
    assert {p.name for p in paths} == {"roadmap-F1abc_-Z.md"}
    assert _front(paths[0])[0]["title"] == "Roadmap 2027"


def test_same_file_from_two_accounts_is_one_note(fake_pipeline):
    store.upsert(_event(account="me@x.com"))
    assert store.upsert(_event(account="me@work.com"))[0] == "skipped"
    assert len(fake_pipeline) == 1


def test_moved_note_is_still_found(fake_pipeline):
    store.upsert(_event())
    ctx_note = next(p for p in store.find_notes("F1abc_-Z") if "20-contexts" in p.parts)
    dest = vault_path() / "20-contexts" / "personal" / "gdrive" / "archive" / ctx_note.name
    dest.parent.mkdir(parents=True)
    ctx_note.rename(dest)
    assert dest in store.find_notes("F1abc_-Z")


def test_other_sources_keep_timestamped_filenames():
    name = note_generator._filename_for(
        {"source": "gmail", "timestamp": "2026-09-01T10:00:00Z", "title": "Hi"}, "gmail:abc")
    assert name.startswith("20260901T100000-hi-")
