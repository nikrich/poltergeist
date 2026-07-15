"""POST /v1/notes/{id}/route validates against configured contexts."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from ghostbrain.api.routes import notes as notes_mod


def _configure(vault, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_configured_context_is_accepted_needs_review_is_not(vault):
    _configure(vault, ["alpha", "beta"])
    assert notes_mod._known_contexts() == {"alpha", "beta"}


def test_route_note_rejects_unconfigured_context(vault):
    _configure(vault, ["alpha"])
    req = notes_mod.RouteNoteRequest(context="sanlam")
    with pytest.raises(HTTPException) as exc:
        notes_mod.route_note(req, jot_id="a" * 12)
    assert exc.value.status_code == 400
    assert "sanlam" in exc.value.detail
