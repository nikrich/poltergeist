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
