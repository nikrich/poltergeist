"""GET /v1/search/status and POST /v1/search/reindex.

Patches the heavy refresh via ``search_repo._do_refresh`` so the embedding
stack (torch/sentence-transformers) is never imported.
"""
import json
import threading
import time

import pytest

from ghostbrain.api.repo import search as search_repo


@pytest.fixture
def tmp_index(tmp_path, monkeypatch):
    d = tmp_path / "semantic"
    d.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(d))
    # Ensure no leaked running state from a prior test.
    search_repo._reindex_state["running"] = False
    return d


def _wait_idle(timeout=2.0):
    deadline = time.time() + timeout
    while search_repo.is_reindex_running() and time.time() < deadline:
        time.sleep(0.02)


def test_status_no_index(client, auth_headers, tmp_index):
    r = client.get("/v1/search/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "lastIndexedAt": None,
        "noteCount": 0,
        "model": None,
        "running": False,
    }


def test_status_reports_count_and_model(client, auth_headers, tmp_index):
    (tmp_index / "index.json").write_text(
        json.dumps(
            {
                "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                "entries": {
                    "20-contexts/sanlam/a.md": {"row": 0, "mtime": 1.0, "hash": "x"},
                    "20-contexts/sanlam/b.md": {"row": 1, "mtime": 2.0, "hash": "y"},
                },
            }
        ),
        encoding="utf-8",
    )
    body = client.get("/v1/search/status", headers=auth_headers).json()
    assert body["noteCount"] == 2
    assert body["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert body["lastIndexedAt"] is not None  # ISO8601 from index.json mtime


def test_reindex_runs_refresh_in_background(client, auth_headers, tmp_index, monkeypatch):
    calls = {"n": 0}

    def fake_refresh():
        calls["n"] += 1

    monkeypatch.setattr(search_repo, "_do_refresh", fake_refresh)
    r = client.post("/v1/search/reindex", headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["started"] is True
    _wait_idle()
    assert calls["n"] == 1
    assert search_repo.is_reindex_running() is False


def test_reindex_conflict_when_already_running(client, auth_headers, tmp_index, monkeypatch):
    gate = threading.Event()

    def slow_refresh():
        gate.wait(timeout=2)

    monkeypatch.setattr(search_repo, "_do_refresh", slow_refresh)
    try:
        r1 = client.post("/v1/search/reindex", headers=auth_headers)
        assert r1.status_code == 202
        # status reflects the in-flight run
        assert client.get("/v1/search/status", headers=auth_headers).json()["running"] is True
        # second request is rejected while one is in flight
        r2 = client.post("/v1/search/reindex", headers=auth_headers)
        assert r2.status_code == 409
        assert r2.json()["started"] is False
    finally:
        gate.set()
        _wait_idle()
