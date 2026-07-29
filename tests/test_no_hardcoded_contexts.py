"""The legacy context names may appear in ghostbrain/ ONLY in
routing_config.py (the back-compat fallback). Everything else must go
through routing_config.contexts().
"""
from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "ghostbrain"
ALLOWED = {PACKAGE / "routing_config.py"}
NAMES = ("sanlam", "codeship", "reducedrecipes")  # "personal" is a legit default


def test_legacy_context_names_only_in_routing_config():
    offenders: list[str] = []
    for f in PACKAGE.rglob("*.py"):
        if f in ALLOWED or "__pycache__" in f.parts or "tests" in f.parts:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for name in NAMES:
            if name in body:
                offenders.append(f"{f.relative_to(PACKAGE.parent)}: {name}")
    assert not offenders, (
        "hardcoded context names found (use ghostbrain.routing_config.contexts()):\n"
        + "\n".join(offenders)
    )


def test_legacy_context_names_not_in_desktop_src():
    """The desktop renderer slipped through the ghostbrain/-only guard and
    shipped the legacy four in three dropdowns (fixed in v1.3.1 via
    GET /v1/vault/contexts + useContexts()). Test files are exempt — they
    stub the endpoint with representative data.
    """
    desktop_src = PACKAGE.parent / "desktop" / "src"
    offenders: list[str] = []
    for f in desktop_src.rglob("*"):
        if f.suffix not in (".ts", ".tsx") or "__tests__" in f.parts:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for name in NAMES:
            if name in body:
                offenders.append(f"{f.relative_to(PACKAGE.parent)}: {name}")
    assert not offenders, (
        "hardcoded context names found in desktop/src (use useContexts()):\n"
        + "\n".join(offenders)
    )
