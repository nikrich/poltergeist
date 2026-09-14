from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo import recorder as repo
from ghostbrain.recorder import audio_capture


@pytest.fixture
def client():
    return TestClient(create_app("tok")), {"Authorization": "Bearer tok"}


def test_missing_prereqs_are_412_with_the_preflight_text(monkeypatch, client):
    c, h = client
    monkeypatch.setattr(repo, "_ensure_supported", lambda: None)
    monkeypatch.setattr(repo, "recorder_prereqs_ok",
                        lambda: (False, ["ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)"]))
    r = c.post("/v1/recorder/start", json={"context": "work"}, headers=h)
    assert r.status_code == 412
    assert "brew install ffmpeg" in r.json()["detail"]


@pytest.mark.skipif(sys.platform != "darwin", reason="patches the darwin capture path")
def test_oserror_from_capture_is_500_with_detail_not_bare(monkeypatch, client):
    c, h = client
    monkeypatch.setattr(repo, "_ensure_supported", lambda: None)
    monkeypatch.setattr(repo, "recorder_prereqs_ok", lambda: (True, []))
    monkeypatch.setattr(repo, "_daemon_active", lambda: None)
    monkeypatch.setattr(repo, "_read_state", lambda: None)

    def boom(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: '/opt/homebrew/bin/ffmpeg'")

    # repo.start() reaches the ffmpeg subprocess wrapper via
    # get_backend().start_capture(), which on darwin (this test env) delegates
    # straight through to ghostbrain.recorder.audio_capture.start_capture —
    # repo.py itself never imports the audio_capture module, so that's the
    # real call site to patch (brief originally assumed a module-level
    # `repo.audio_capture` reference that doesn't exist).
    monkeypatch.setattr(audio_capture, "start_capture", boom)
    r = c.post("/v1/recorder/start", json={"context": "work"}, headers=h)
    assert r.status_code == 500
    assert "/opt/homebrew/bin/ffmpeg" in r.json()["detail"]


def test_prereqs_moved_and_reexported():
    from ghostbrain import scheduler_jobs
    from ghostbrain.recorder import prereqs

    assert scheduler_jobs.recorder_prereqs_ok is prereqs.recorder_prereqs_ok
