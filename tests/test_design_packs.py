"""Design-system pack library: builtin pack, vault library, agent-driven import."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from ghostbrain.design import packs
from ghostbrain.design import settings as design_settings


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def _make_pack(vault: Path, pack_id: str, name: str = "Acme") -> Path:
    d = vault / "90-meta" / "design-systems" / pack_id
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({
        "id": pack_id, "name": name, "source": "/tmp/acme", "imported_at": "2026-10-10T00:00:00+00:00",
    }))
    (d / "tokens.css").write_text(":root { --ds-color-primary: #f00; }\n")
    (d / "README.md").write_text("# Acme\n")
    return d


def _wait(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = packs.get_import(job_id)
        if job and job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("import job did not finish")


# --- library ---------------------------------------------------------------


def test_library_dir_is_under_vault_meta(vault: Path):
    assert packs.library_dir() == vault / "90-meta" / "design-systems"


def test_builtin_pack_ships_tokens_and_readme(vault: Path):
    d = packs.pack_dir(packs.BUILTIN_PACK_ID)
    tokens = (d / "tokens.css").read_text()
    assert "--ds-color-" in tokens and "--ds-font-" in tokens and "--ds-space-" in tokens
    assert "--ds-radius-" in tokens and "--ds-shadow-" in tokens
    for sel in ("body", "h1", "button", "input", "table"):
        assert sel in tokens
    assert (d / "README.md").read_text().strip()
    meta = json.loads((d / "pack.json").read_text())
    assert meta["id"] == packs.BUILTIN_PACK_ID


def test_list_packs_builtin_first_then_library(vault: Path):
    _make_pack(vault, "zeta", "Zeta")
    _make_pack(vault, "acme", "Acme")
    listed = packs.list_packs()
    assert listed[0] == {
        "id": packs.BUILTIN_PACK_ID,
        "name": listed[0]["name"],
        "source": listed[0]["source"],
        "imported_at": None,
        "builtin": True,
    }
    assert [p["id"] for p in listed[1:]] == ["acme", "zeta"]
    assert listed[1] == {
        "id": "acme", "name": "Acme", "source": "/tmp/acme",
        "imported_at": "2026-10-10T00:00:00+00:00", "builtin": False,
    }


def test_list_skips_staging_and_incomplete_dirs(vault: Path):
    lib = vault / "90-meta" / "design-systems"
    (lib / ".staging" / "job").mkdir(parents=True)
    (lib / "half").mkdir()  # no pack.json
    assert [p["id"] for p in packs.list_packs()] == [packs.BUILTIN_PACK_ID]


def test_get_pack_and_pack_dir(vault: Path):
    d = _make_pack(vault, "acme")
    assert packs.get_pack("acme")["name"] == "Acme"
    assert packs.pack_dir("acme") == d
    assert packs.get_pack("nope") is None
    with pytest.raises(KeyError):
        packs.pack_dir("nope")


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "", ".staging", "A B", "/etc"])
def test_rejects_traversal_and_bad_ids(vault: Path, bad: str):
    assert packs.get_pack(bad) is None
    with pytest.raises(KeyError):
        packs.pack_dir(bad)
    with pytest.raises(KeyError):
        packs.delete_pack(bad)


def test_copy_into_replaces_destination(vault: Path, tmp_path: Path):
    _make_pack(vault, "acme")
    dest = tmp_path / "proto" / "design-pack"
    dest.mkdir(parents=True)
    (dest / "stale.css").write_text("old")
    packs.copy_into("acme", dest)
    assert not (dest / "stale.css").exists()
    assert "#f00" in (dest / "tokens.css").read_text()
    packs.copy_into(packs.BUILTIN_PACK_ID, dest)
    assert "#f00" not in (dest / "tokens.css").read_text()
    with pytest.raises(KeyError):
        packs.copy_into("nope", dest)


def test_delete_pack(vault: Path):
    d = _make_pack(vault, "acme")
    packs.delete_pack("acme")
    assert not d.exists()
    with pytest.raises(ValueError):
        packs.delete_pack(packs.BUILTIN_PACK_ID)
    with pytest.raises(KeyError):
        packs.delete_pack("acme")


# --- import ----------------------------------------------------------------


@pytest.fixture
def fake_claude(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(packs, "_find_claude_binary", lambda: "/usr/bin/claude")


def _agent(write: dict[str, str] | None, *, rc: int = 0, result: str = "done", calls=None):
    def run(cmd, cwd, timeout):
        if calls is not None:
            calls.append({"cmd": cmd, "cwd": Path(cwd), "timeout": timeout})
        for rel, text in (write or {}).items():
            p = Path(cwd) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        out = json.dumps({"type": "result", "is_error": rc != 0, "result": result})
        return subprocess.CompletedProcess(cmd, rc, out, "stderr tail")
    return run


def test_import_success_moves_staging_into_library(vault: Path, fake_claude, monkeypatch):
    calls: list = []
    monkeypatch.setattr(packs, "_run_agent", _agent({
        "tokens.css": ":root { --ds-color-primary: #123456; }",
        "README.md": "# Brand\n",
        "assets/logo.svg": "<svg/>",
        "reference/home.md": "home screen",
    }, calls=calls))
    job = packs.start_import("https://claude.ai/design/p/abc123", name="Acme Brand")
    assert job["status"] == "running" and job["source"] == "https://claude.ai/design/p/abc123"
    done = _wait(job["id"])
    assert done == {
        "id": job["id"], "source": "https://claude.ai/design/p/abc123",
        "status": "done", "message": None, "pack_id": "acme-brand",
    }
    d = vault / "90-meta" / "design-systems" / "acme-brand"
    assert (d / "assets" / "logo.svg").exists() and (d / "reference" / "home.md").exists()
    meta = json.loads((d / "pack.json").read_text())
    assert meta["id"] == "acme-brand" and meta["name"] == "Acme Brand"
    assert meta["source"] == "https://claude.ai/design/p/abc123" and meta["imported_at"]
    # staging is cleaned up
    assert not any((vault / "90-meta" / "design-systems" / ".staging").glob("*"))

    cmd = calls[0]["cmd"]
    assert cmd[0] == "/usr/bin/claude" and "-p" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    tools = cmd[cmd.index("--allowedTools") + 1]
    assert "DesignSync" in tools and "WebFetch" not in tools and "Write(./**)" in tools
    assert "--system-prompt" not in cmd
    assert "--append-system-prompt" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == str(calls[0]["cwd"])
    assert "https://claude.ai/design/p/abc123" in cmd[-1]
    assert calls[0]["cwd"].parent.name == ".staging"


def test_import_unique_id_and_derived_name(vault: Path, fake_claude, monkeypatch):
    _make_pack(vault, "acme-ui")
    monkeypatch.setattr(packs, "_run_agent", _agent({
        "tokens.css": ":root { --x: 1; }", "README.md": "# Acme UI\n\nrules",
    }))
    done = _wait(packs.start_import("/Users/me/acme")["id"])
    assert done["status"] == "done" and done["pack_id"] == "acme-ui-2"
    assert packs.get_pack("acme-ui-2")["name"] == "Acme UI"


def test_import_never_shadows_builtin(vault: Path, fake_claude, monkeypatch):
    monkeypatch.setattr(packs, "_run_agent", _agent({"tokens.css": "--a: 1;", "README.md": "x"}))
    done = _wait(packs.start_import("x", name="Poltergeist Neutral")["id"])
    assert done["pack_id"] == "poltergeist-neutral-2"


@pytest.mark.parametrize("files", [
    {"README.md": "# x"},  # no tokens
    {"tokens.css": "", "README.md": "# x"},  # empty tokens
    {"tokens.css": "body { color: red }", "README.md": "# x"},  # no custom properties
    {"tokens.css": ":root{--a:1}"},  # no readme
])
def test_import_validation_failure_writes_nothing(vault: Path, fake_claude, monkeypatch, files):
    monkeypatch.setattr(packs, "_run_agent", _agent(files, result="I could not reach the source"))
    done = _wait(packs.start_import("nowhere", name="Broken")["id"])
    assert done["status"] == "error" and done["pack_id"] is None
    assert "I could not reach the source" in done["message"]
    assert [p["id"] for p in packs.list_packs()] == [packs.BUILTIN_PACK_ID]
    assert not any((vault / "90-meta" / "design-systems" / ".staging").glob("*"))


def test_import_agent_error_reports_message(vault: Path, fake_claude, monkeypatch):
    monkeypatch.setattr(packs, "_run_agent", _agent(
        {"tokens.css": ":root{--a:1}", "README.md": "x"}, rc=1, result="budget exceeded",
    ))
    done = _wait(packs.start_import("src")["id"])
    assert done["status"] == "error" and "budget exceeded" in done["message"]


def test_import_stderr_tail_when_no_json(vault: Path, fake_claude, monkeypatch):
    def run(cmd, cwd, timeout):
        return subprocess.CompletedProcess(cmd, 2, "not json", "boom: auth required")
    monkeypatch.setattr(packs, "_run_agent", run)
    done = _wait(packs.start_import("src")["id"])
    assert done["status"] == "error" and "auth required" in done["message"]


def test_import_runner_exception_becomes_error(vault: Path, fake_claude, monkeypatch):
    def run(cmd, cwd, timeout):
        raise TimeoutError("timed out after 900s")
    monkeypatch.setattr(packs, "_run_agent", run)
    done = _wait(packs.start_import("src")["id"])
    assert done["status"] == "error" and "timed out" in done["message"]


def test_import_without_claude_cli(vault: Path, monkeypatch):
    monkeypatch.setattr(packs, "_find_claude_binary", lambda: None)
    done = _wait(packs.start_import("src")["id"])
    assert done["status"] == "error" and "claude" in done["message"].lower()


def test_import_rejects_blank_source(vault: Path):
    with pytest.raises(ValueError):
        packs.start_import("   ")


def test_get_import_unknown(vault: Path):
    assert packs.get_import("nope") is None


# --- settings ----------------------------------------------------------------


def test_settings_defaults(vault: Path):
    assert design_settings.load() == {
        "listen": True, "budget_usd": 2.0, "default_pack": packs.BUILTIN_PACK_ID,
        "code_roots": ["~/development"], "web": True,
    }


def test_settings_update_persists_and_preserves_other_config(vault: Path):
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("recorder:\n  enabled: false\n")
    _make_pack(vault, "acme")
    out = design_settings.update(listen=False, budget_usd=5, default_pack="acme")
    assert out == {
        "listen": False, "budget_usd": 5.0, "default_pack": "acme", "code_roots": ["~/development"], "web": True,
    }
    assert design_settings.load() == out
    import yaml
    data = yaml.safe_load(cfg.read_text())
    assert data["recorder"] == {"enabled": False}
    assert data["design"]["budget_usd"] == 5.0
    # None fields are left alone
    assert design_settings.update(listen=None) == out


@pytest.mark.parametrize("fields", [
    {"budget_usd": 0.05}, {"budget_usd": 25}, {"default_pack": "nope"}, {"bogus": 1},
])
def test_settings_update_validation(vault: Path, fields):
    with pytest.raises(ValueError):
        design_settings.update(**fields)


def test_settings_load_tolerates_garbage_and_deleted_pack(vault: Path):
    (vault / "90-meta" / "config.yaml").write_text(
        "design:\n  listen: nope\n  budget_usd: lots\n  default_pack: gone\n"
    )
    assert design_settings.load() == {
        "listen": True, "budget_usd": 2.0, "default_pack": packs.BUILTIN_PACK_ID,
        "code_roots": ["~/development"], "web": True,
    }


# -- importer least privilege ---------------------------------------------------

def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def _cmd(source, tmp_path):
    from ghostbrain.design import packs
    return packs._command("claude", tmp_path / "stage", source)


def test_import_writes_stay_in_staging_and_nothing_is_asked(tmp_path):
    for source in ("https://brand.example.com", "Acme design system", str(tmp_path)):
        cmd = _cmd(source, tmp_path)
        assert _flag(cmd, "--permission-mode") == "dontAsk"
        tools = _flag(cmd, "--allowedTools").split(",")
        assert "Write(./**)" in tools and "Edit(./**)" in tools
        assert "Write" not in tools and "Bash" not in tools


def test_local_folder_import_reads_the_folder_without_network_or_connectors(tmp_path):
    src = tmp_path / "brand"
    src.mkdir()
    cmd = _cmd(str(src), tmp_path)
    tools = _flag(cmd, "--allowedTools").split(",")
    assert "WebFetch" not in tools and "DesignSync" not in tools
    assert "--strict-mcp-config" in cmd
    assert str(src.resolve()) in cmd[cmd.index("--add-dir") + 1:cmd.index("--add-dir") + 3]


def test_web_import_fetches_but_gets_no_connectors(tmp_path):
    cmd = _cmd("https://brand.example.com/guidelines", tmp_path)
    tools = _flag(cmd, "--allowedTools").split(",")
    assert "WebFetch" in tools and "DesignSync" not in tools
    assert "--strict-mcp-config" in cmd


def test_claude_design_import_uses_designsync_only(tmp_path):
    for source in ("https://claude.ai/design/p/019e0144", "Acme Design System"):
        cmd = _cmd(source, tmp_path)
        tools = _flag(cmd, "--allowedTools").split(",")
        assert "DesignSync" in tools and "WebFetch" not in tools
        assert "--strict-mcp-config" in cmd


def test_figma_import_keeps_mcp_servers_but_no_web(tmp_path):
    cmd = _cmd("https://www.figma.com/design/abc/Brand", tmp_path)
    tools = _flag(cmd, "--allowedTools").split(",")
    assert "WebFetch" not in tools
    assert "--strict-mcp-config" not in cmd
    assert any(t.lower().startswith("mcp__") and "figma" in t.lower() for t in tools)
