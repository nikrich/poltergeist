from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from ghostbrain.doctor.fixes import models


@pytest.fixture
def served(tmp_path: Path):
    """Serve tmp_path/srv over HTTP; yields (base_url, srv_dir)."""
    srv = tmp_path / "srv"
    srv.mkdir()
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(srv), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", srv
    httpd.shutdown()


def test_download_writes_part_then_renames(served, tmp_path: Path):
    base, srv = served
    (srv / "ggml-base.en.bin").write_bytes(b"m" * 5000)
    dest = tmp_path / "models"
    seen: list[tuple[int, int]] = []
    out = models.download("base.en", dest, base_url=base, progress=lambda done, total: seen.append((done, total)))
    assert out == dest / "ggml-base.en.bin"
    assert out.read_bytes() == b"m" * 5000
    assert not list(dest.glob("*.part"))
    assert seen[-1] == (5000, 5000)


def test_size_mismatch_is_failure_and_leaves_no_part(served, tmp_path: Path, monkeypatch):
    base, srv = served
    (srv / "ggml-base.en.bin").write_bytes(b"m" * 100)
    monkeypatch.setattr(models, "_content_length", lambda resp: 999)
    with pytest.raises(models.FetchError):
        models.download("base.en", tmp_path / "models", base_url=base, progress=lambda d, t: None)
    assert not list((tmp_path / "models").glob("*"))


def test_main_default_is_medium_and_skips_when_present(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(models, "DEFAULT_MODEL_DIR", tmp_path)
    (tmp_path / "ggml-medium.en.bin").write_bytes(b"x")
    assert models.main([]) == 0
    assert "already present" in capsys.readouterr().out


def test_main_respects_env_override(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("GHOSTBRAIN_WHISPER_MODEL", str(tmp_path / "custom.bin"))
    assert models.main([]) == 0
    assert "GHOSTBRAIN_WHISPER_MODEL" in capsys.readouterr().out


def test_main_rejects_unknown_model(capsys):
    assert models.main(["huge"]) == 2
    assert "base.en, small.en, medium.en" in capsys.readouterr().err
