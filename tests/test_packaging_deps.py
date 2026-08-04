"""Guards on the dependency extras the PyInstaller bundle is built from.

The packaged `ghostbrain-api` doubles as the Poltergeist MCP stdio server via its
`mcp` subcommand. The release workflow builds the bundle from `pip install -e
".[api,semantic]"`, so anything that subcommand imports at startup must resolve
to a package installed by one of those extras — otherwise the frozen
`ghostbrain-api mcp` dies with `ModuleNotFoundError` and vault chat can never
connect (the bug behind v0.3.3/v0.3.4).
"""
from __future__ import annotations

import pathlib
import tomllib

_PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"


def _dist_names(deps: list[str]) -> set[str]:
    names = set()
    for dep in deps:
        # "mcp>=1.2.0" / "uvicorn[standard]>=0.32" -> "mcp" / "uvicorn"
        name = dep.split(";")[0].strip()
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            name = name.split(sep)[0]
        names.add(name.strip().lower())
    return names


def test_api_extra_includes_mcp_so_bundle_can_serve_mcp():
    extras = tomllib.loads(_PYPROJECT.read_text())["project"]["optional-dependencies"]
    api_names = _dist_names(extras["api"])
    assert "mcp" in api_names, (
        "the `mcp` library must be in the [api] extra (what the PyInstaller build "
        f"installs); frozen `ghostbrain-api mcp` imports it. Got: {sorted(api_names)}"
    )
