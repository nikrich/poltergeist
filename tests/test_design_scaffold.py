"""Prototype scaffold: template copy, git revisions, revert, eject."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ghostbrain.design import packs, scaffold

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    # Never let the developer's global git config/hooks leak into the test repo.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "nogitconfig"))
    return v


@pytest.fixture
def proto(vault: Path, tmp_path: Path) -> Path:
    d = tmp_path / "vault" / "20-contexts" / "work" / "prototypes" / "2026-10-10-checkout"
    scaffold.create(d, packs.BUILTIN_PACK_ID, title='Checkout "flow"')
    return d


def _log(d: Path) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s"], cwd=d, capture_output=True, text=True, check=True,
    )
    return out.stdout.splitlines()


def test_create_lays_out_template_pack_and_rev0(proto: Path):
    for f in ("main.tsx", "App.tsx", "router.tsx", "data.ts", "styles.css"):
        assert (proto / "src" / f).is_file(), f
    assert (proto / "design-pack" / "tokens.css").is_file()
    assert (proto / "design-pack" / "README.md").is_file()
    gi = (proto / ".gitignore").read_text()
    assert "dist/" in gi and "node_modules/" in gi
    assert _log(proto) == ["rev 0: scaffold"]
    # The title lands in App.tsx as a safe string literal.
    app = (proto / "src" / "App.tsx").read_text()
    assert json.dumps('Checkout "flow"') in app
    assert "__PROTOTYPE_TITLE__" not in app


def test_template_only_imports_react_and_relative_files(proto: Path):
    allowed = {"react", "react-dom/client"}
    for f in (proto / "src").glob("*.ts*"):
        for spec in re.findall(r"""(?:from|import)\s+['"]([^'"]+)['"]""", f.read_text()):
            assert spec in allowed or spec.startswith("./"), f"{f.name}: {spec}"


def test_commit_and_revisions(proto: Path):
    (proto / "src" / "App.tsx").write_text("export default function App() { return null; }\n")
    sha = scaffold.commit(proto, "rev 1: checkout screen")
    assert re.fullmatch(r"[0-9a-f]{4,40}", sha)
    revs = scaffold.revisions(proto)
    assert [(r["rev"], r["summary"]) for r in revs] == [(0, "scaffold"), (1, "checkout screen")]
    assert all(r["at"] for r in revs)


def test_commit_with_no_changes_still_records_a_rev(proto: Path):
    scaffold.commit(proto, "rev 1: nothing new")
    assert [r["rev"] for r in scaffold.revisions(proto)] == [0, 1]


def test_revert_to_restores_only_src(proto: Path):
    original = (proto / "src" / "App.tsx").read_text()
    (proto / "src" / "App.tsx").write_text("// v1\n")
    (proto / "src" / "Extra.tsx").write_text("// added in rev 1\n")
    scaffold.commit(proto, "rev 1: extra screen")
    (proto / "board.json").write_text('{"items": [1]}')
    scaffold.commit(proto, "board 1: first events")
    (proto / "src" / "App.tsx").write_text("// v2\n")
    (proto / "board.json").write_text('{"items": [1, 2]}')
    scaffold.commit(proto, "rev 2: tweak")

    scaffold.revert_to(proto, 0)
    assert (proto / "src" / "App.tsx").read_text() == original
    assert not (proto / "src" / "Extra.tsx").exists()
    assert (proto / "board.json").read_text() == '{"items": [1, 2]}'  # untouched
    assert _log(proto)[0] == "revert to rev 0"
    # Revert commits and board commits are not UI revisions.
    assert [r["rev"] for r in scaffold.revisions(proto)] == [0, 1, 2]

    scaffold.revert_to(proto, 2)
    assert (proto / "src" / "App.tsx").read_text() == "// v2\n"
    assert (proto / "src" / "Extra.tsx").exists()


def test_create_tolerates_existing_files(vault: Path, tmp_path: Path):
    d = tmp_path / "p"
    d.mkdir()
    (d / "board.json").write_text("{}")
    (d / "session.jsonl").write_text("{}\n")
    scaffold.create(d, packs.BUILTIN_PACK_ID, title="x")
    assert (d / "board.json").read_text() == "{}"
    assert _log(d) == ["rev 0: scaffold"]
    assert scaffold.revisions(d)[0]["rev"] == 0


def test_revert_to_unknown_rev(proto: Path):
    with pytest.raises(KeyError):
        scaffold.revert_to(proto, 7)


def test_eject_writes_vite_project(proto: Path):
    out = scaffold.eject(proto)
    assert out == proto
    pkg = json.loads((proto / "package.json").read_text())
    assert pkg["dependencies"]["react"] == "18.3.1"
    assert pkg["dependencies"]["react-dom"] == "18.3.1"
    assert {"vite", "@vitejs/plugin-react", "typescript"} <= set(pkg["devDependencies"])
    assert "dev" in pkg["scripts"]
    assert "plugin-react" in (proto / "vite.config.ts").read_text()
    html = (proto / "index.html").read_text()
    assert "./design-pack/tokens.css" in html and "/src/main.tsx" in html
    assert 'id="root"' in html


def test_git_missing_degrades(vault: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(scaffold, "_git_bin", lambda: None)
    d = tmp_path / "p"
    scaffold.create(d, packs.BUILTIN_PACK_ID, title="x")
    assert (d / "src" / "App.tsx").exists() and not (d / ".git").exists()
    assert scaffold.commit(d, "rev 1: x") == ""
    assert scaffold.revisions(d) == []
