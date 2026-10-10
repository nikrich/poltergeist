"""``design.code_roots``: folders searched for existing codebases."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.design import settings


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_code_roots_default_and_update(vault: Path):
    assert settings.load()["code_roots"] == ["~/development"]
    assert settings.update(code_roots=["~/dev", " "])["code_roots"] == ["~/dev"]


def test_code_roots_strips_keeps_order_and_dedupes(vault: Path):
    out = settings.update(code_roots=[" ~/b ", "~/a", "~/b"])
    assert out["code_roots"] == ["~/b", "~/a"]
    assert settings.load()["code_roots"] == ["~/b", "~/a"]


def test_code_roots_empty_list_falls_back_to_default(vault: Path):
    assert settings.update(code_roots=[])["code_roots"] == ["~/development"]


@pytest.mark.parametrize("bad", ["~/dev", [1], [f"~/r{i}" for i in range(11)]])
def test_code_roots_validation(vault: Path, bad):
    with pytest.raises(ValueError):
        settings.update(code_roots=bad)


def test_code_roots_load_tolerates_garbage(vault: Path):
    (vault / "90-meta" / "config.yaml").write_text("design:\n  code_roots: nope\n")
    assert settings.load()["code_roots"] == ["~/development"]
    (vault / "90-meta" / "config.yaml").write_text("design:\n  code_roots: [3, '', '~/x']\n")
    assert settings.load()["code_roots"] == ["~/x"]


def test_settings_route_accepts_code_roots(vault: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ghostbrain.api.routes import design_packs

    app = FastAPI()
    app.include_router(design_packs.router)
    client = TestClient(app)
    assert client.get("/v1/design/settings").json()["code_roots"] == ["~/development"]
    r = client.put("/v1/design/settings", json={"code_roots": ["~/work"]})
    assert r.status_code == 200 and r.json()["code_roots"] == ["~/work"]
    assert client.put("/v1/design/settings", json={"listen": False}).json()["code_roots"] == ["~/work"]
    bad = client.put("/v1/design/settings", json={"code_roots": [f"~/r{i}" for i in range(11)]})
    assert bad.status_code == 422
