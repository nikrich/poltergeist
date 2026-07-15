"""api.__main__ entrypoint dispatch.

The packaged build ships a single `ghostbrain-api` executable. It doubles as the
Poltergeist MCP stdio server (so chat has vault tools without a second, ML-heavy
PyInstaller bundle) by recognising an `mcp` subcommand and delegating instead of
booting uvicorn.

Crucially, the `mcp` path must stay decoupled from the api app: the MCP stdio
server only needs the lightweight, self-contained `ghostbrain.mcp` tree. If the
entrypoint eagerly imports `ghostbrain.api.main` (the full route tree) at module
load, the frozen `ghostbrain-api mcp` subprocess pays for — and can crash or
stall on — that import before the MCP handshake completes, which surfaces in
chat as "the poltergeist vault server is still connecting".
"""
from __future__ import annotations

import subprocess
import sys

import ghostbrain.mcp.__main__ as mcp_main_mod
import ghostbrain.api.__main__ as api_main_mod
from ghostbrain.api.__main__ import main


def test_main_dispatches_mcp_subcommand(monkeypatch):
    ran = {}
    monkeypatch.setattr(mcp_main_mod, "main", lambda: ran.setdefault("mcp", True))
    # The api-server path must NOT run for the mcp subcommand.
    monkeypatch.setattr(
        api_main_mod,
        "_run_api_server",
        lambda: (_ for _ in ()).throw(AssertionError("api server booted for mcp subcommand")),
    )

    rc = main(["mcp"])

    assert rc == 0
    assert ran.get("mcp") is True


def test_main_without_subcommand_runs_api_server(monkeypatch):
    monkeypatch.setattr(
        mcp_main_mod,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("MCP path taken for normal boot")),
    )
    ran = {}
    monkeypatch.setattr(api_main_mod, "_run_api_server", lambda: ran.setdefault("api", 0) or 0)

    rc = main([])

    assert rc == 0
    assert "api" in ran


def test_entrypoint_import_does_not_eagerly_import_api_app():
    """Importing the entrypoint must not drag in `ghostbrain.api.main`. The MCP
    subcommand depends on this isolation — coupling broke packaged vault chat."""
    code = (
        "import importlib, sys; "
        "importlib.import_module('ghostbrain.api.__main__'); "
        "assert 'ghostbrain.api.main' not in sys.modules, "
        "'entrypoint eagerly imported the api route tree'; "
        "print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_ensure_vault_bootstraps_when_missing(vault_empty):
    from ghostbrain.api.__main__ import ensure_vault

    assert not (vault_empty / "90-meta" / "routing.yaml").exists()
    ensure_vault()
    assert (vault_empty / "90-meta" / "routing.yaml").exists()


def test_ensure_vault_is_noop_when_vault_exists(vault_empty):
    from ghostbrain.api.__main__ import ensure_vault

    marker = vault_empty / "90-meta" / "routing.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("sentinel: true\n", encoding="utf-8")

    ensure_vault()

    assert marker.read_text() == "sentinel: true\n"
    # No other bootstrap artifacts were created.
    assert not (vault_empty / "20-contexts").exists()


def test_ensure_vault_swallows_bootstrap_errors(vault_empty, monkeypatch):
    import ghostbrain.bootstrap as bootstrap_mod
    from ghostbrain.api.__main__ import ensure_vault

    def boom() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(bootstrap_mod, "bootstrap", boom)
    ensure_vault()  # must not raise — sidecar would crash-loop otherwise


def test_ensure_vault_swallows_vault_path_errors(monkeypatch):
    import ghostbrain.paths as paths_mod
    from ghostbrain.api.__main__ import ensure_vault

    def boom() -> None:
        raise RuntimeError("boom")

    # ensure_vault imports vault_path lazily from ghostbrain.paths, so
    # patching the module attribute is what its `from ... import` sees.
    monkeypatch.setattr(paths_mod, "vault_path", boom)
    ensure_vault()  # must not raise — sidecar would crash-loop otherwise
