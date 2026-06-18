"""api.__main__ entrypoint dispatch.

The packaged build ships a single `ghostbrain-api` executable. It doubles as the
Poltergeist MCP stdio server (so chat has vault tools without a second, ML-heavy
PyInstaller bundle) by recognising an `mcp` subcommand and delegating instead of
booting uvicorn.
"""
from __future__ import annotations

import ghostbrain.mcp.__main__ as mcp_main_mod
from ghostbrain.api.__main__ import main


def test_main_dispatches_mcp_subcommand(monkeypatch):
    ran = {}
    monkeypatch.setattr(mcp_main_mod, "main", lambda: ran.setdefault("mcp", True))

    rc = main(["mcp"])

    assert rc == 0
    assert ran.get("mcp") is True


def test_main_does_not_dispatch_mcp_without_subcommand(monkeypatch):
    """No `mcp` arg must NOT delegate — otherwise the normal sidecar boot path
    would be shadowed. We stub the MCP main to explode if wrongly called and
    stop just before uvicorn so the test stays hermetic."""
    monkeypatch.setattr(
        mcp_main_mod,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("MCP path taken for normal boot")),
    )

    import ghostbrain.api.__main__ as api_main_mod

    monkeypatch.setattr(
        api_main_mod.uvicorn,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(SystemExit(0)),
    )
    monkeypatch.setattr(api_main_mod, "_publish_descriptor", lambda **k: None)

    # Reaching uvicorn.run (our SystemExit sentinel) proves we took the normal
    # path, not the MCP branch.
    try:
        main([])
    except SystemExit:
        pass
