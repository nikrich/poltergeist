"""The legacy context names must not appear anywhere in the codebase.

The repo is public: these names identify the original author's contexts
(one of them an employer), so they are banned outright — code goes through
routing_config.contexts(), examples use neutral placeholders.
"""
from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "ghostbrain"
NAMES = ("sanlam", "codeship", "reducedrecipes")  # "personal" is a legit default


def test_legacy_context_names_not_in_package():
    offenders: list[str] = []
    for f in PACKAGE.rglob("*.py"):
        if "__pycache__" in f.parts or "tests" in f.parts:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for name in NAMES:
            if name in body:
                offenders.append(f"{f.relative_to(PACKAGE.parent)}: {name}")
    assert not offenders, (
        "hardcoded context names found (use ghostbrain.routing_config.contexts()):\n"
        + "\n".join(offenders)
    )


def test_legacy_context_names_not_in_docs():
    """Design docs and specs are published with the repo — same ban."""
    root = PACKAGE.parent
    offenders: list[str] = []
    for base in (root / "docs", root / "spec"):
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in (".md", ".html", ".yaml"):
                continue
            body = f.read_text(encoding="utf-8", errors="replace").lower()
            for name in NAMES:
                if name in body:
                    offenders.append(f"{f.relative_to(root)}: {name}")
    assert not offenders, (
        "employer/context names found in published docs:\n" + "\n".join(offenders)
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
