"""POST /v1/notes/{jot_id}/route-auto — auto-route an existing jot by re-reading its body.

Tests follow the conftest tmp_vault / client / auth_headers fixtures from
test_routes_notes_create.py.
"""
import frontmatter
import pytest

from ghostbrain.worker.router import RoutingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIDENT = RoutingDecision(
    context="sanlam",
    confidence=0.82,
    reasoning="matches sanlam",
    method="llm",
    secondary_contexts=[],
)

_LOW_CONFIDENCE = RoutingDecision(
    context="needs_review",
    confidence=0.0,
    reasoning="no classifiable content",
    method="fallback",
    secondary_contexts=[],
)


def _create_pending_jot(client, auth_headers, tmp_vault, monkeypatch):
    """Create a jot with route=false (pending state), return response data."""
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: (_ for _ in ()).throw(AssertionError("route_event must not be called")),
    )
    resp = client.post(
        "/v1/notes",
        json={"body": "some real content here", "route": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# POST /v1/notes with route=false — pending, no route_event
# ---------------------------------------------------------------------------


def test_create_with_route_false_returns_pending(
    tmp_vault, client, auth_headers, monkeypatch
):
    """Creating with route=false must not call route_event and return pending."""
    route_event_called = []

    def should_not_be_called(event, **kw):
        route_event_called.append(event)
        return _CONFIDENT

    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event", should_not_be_called
    )

    resp = client.post(
        "/v1/notes",
        json={"body": "draft note content", "route": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "pending"
    assert data["path"].startswith("00-inbox/raw/manual/")
    # route_event must NOT have been called
    assert route_event_called == []


def test_create_with_route_false_file_stays_in_inbox(
    tmp_vault, client, auth_headers, monkeypatch
):
    """File must remain in inbox (not moved to a context folder)."""
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _CONFIDENT,
    )

    resp = client.post(
        "/v1/notes",
        json={"body": "stays in inbox", "route": False},
        headers=auth_headers,
    )
    data = resp.json()
    assert data["routingStatus"] == "pending"
    assert data["path"].startswith("00-inbox/raw/manual/")
    # File must exist at the returned path inside the vault
    assert (tmp_vault / data["path"]).exists()


def test_create_with_route_true_still_routes(
    tmp_vault, client, auth_headers, monkeypatch
):
    """route=true (default) must still call route_event — no regression."""
    (tmp_vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _CONFIDENT,
    )

    resp = client.post(
        "/v1/notes",
        json={"body": "route me to sanlam", "route": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["routingStatus"] == "routed"


# ---------------------------------------------------------------------------
# POST /v1/notes/{jot_id}/route-auto
# ---------------------------------------------------------------------------


def test_route_auto_confident_decision_moves_file(
    tmp_vault, client, auth_headers, monkeypatch
):
    """Confident route_event decision → file moves, status=routed."""
    (tmp_vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)

    # Create pending jot
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _CONFIDENT,
    )
    create_resp = client.post(
        "/v1/notes",
        json={"body": "some real content here", "route": False},
        headers=auth_headers,
    )
    jot_id = create_resp.json()["id"]

    # Restore confident mock for route-auto
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _CONFIDENT,
    )

    resp = client.post(
        f"/v1/notes/{jot_id}/route-auto",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "routed"
    assert data["path"].startswith("20-contexts/sanlam/notes/")
    # File must have moved
    fm = frontmatter.load(tmp_vault / data["path"])
    assert fm["context"] == "sanlam"
    assert fm["routingStatus"] == "routed"


def test_route_auto_low_confidence_marks_manual_review(
    tmp_vault, client, auth_headers, monkeypatch
):
    """Low-confidence decision → routingStatus=manual_review, file stays in inbox."""
    # Create pending jot (skip routing)
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _LOW_CONFIDENCE,
    )
    create_resp = client.post(
        "/v1/notes",
        json={"body": "ambiguous content", "route": False},
        headers=auth_headers,
    )
    jot_id = create_resp.json()["id"]

    resp = client.post(
        f"/v1/notes/{jot_id}/route-auto",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "manual_review"
    assert data["path"].startswith("00-inbox/raw/manual/")


def test_route_auto_unknown_id_returns_404(
    tmp_vault, client, auth_headers
):
    """Unknown jot id → 404."""
    resp = client.post(
        "/v1/notes/manual-20260101T000000-nonexistent/route-auto",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_route_auto_router_exception_falls_back_to_manual_review(
    tmp_vault, client, auth_headers, monkeypatch
):
    """Router exception → manual_review (never raises to caller)."""
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _LOW_CONFIDENCE,
    )
    create_resp = client.post(
        "/v1/notes",
        json={"body": "exception test", "route": False},
        headers=auth_headers,
    )
    jot_id = create_resp.json()["id"]

    def boom(event, **kw):
        raise RuntimeError("LLM timeout")

    monkeypatch.setattr("ghostbrain.api.repo.notes_manual.route_event", boom)

    resp = client.post(
        f"/v1/notes/{jot_id}/route-auto",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["routingStatus"] == "manual_review"


def test_route_auto_reads_current_body(
    tmp_vault, client, auth_headers, monkeypatch
):
    """route-auto uses the jot's CURRENT body (after an update), not the creation body."""
    (tmp_vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _LOW_CONFIDENCE,
    )
    create_resp = client.post(
        "/v1/notes",
        json={"body": "original placeholder body", "route": False},
        headers=auth_headers,
    )
    jot_id = create_resp.json()["id"]

    # Update the body to real content
    client.patch(
        f"/v1/notes/{jot_id}",
        json={"body": "updated sanlam content"},
        headers=auth_headers,
    )

    # Now route-auto should see the updated body
    seen_bodies = []
    def capture_route(event, **kw):
        seen_bodies.append(event.get("body", ""))
        return _CONFIDENT

    monkeypatch.setattr("ghostbrain.api.repo.notes_manual.route_event", capture_route)

    resp = client.post(
        f"/v1/notes/{jot_id}/route-auto",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert seen_bodies == ["updated sanlam content"]


def test_both_route_endpoints_coexist(
    tmp_vault, client, auth_headers, monkeypatch
):
    """Both /route and /route-auto endpoints must be reachable without conflict."""
    (tmp_vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _LOW_CONFIDENCE,
    )
    create_resp = client.post(
        "/v1/notes",
        json={"body": "coexistence test", "route": False},
        headers=auth_headers,
    )
    jot_id = create_resp.json()["id"]

    # /route (manual context selection) — should work
    route_resp = client.post(
        f"/v1/notes/{jot_id}/route",
        json={"context": "sanlam"},
        headers=auth_headers,
    )
    assert route_resp.status_code == 200, route_resp.json()

    # Jot is now routed; re-create a fresh one for route-auto
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: _LOW_CONFIDENCE,
    )
    create_resp2 = client.post(
        "/v1/notes",
        json={"body": "route-auto test", "route": False},
        headers=auth_headers,
    )
    jot_id2 = create_resp2.json()["id"]

    # /route-auto — should also work
    auto_resp = client.post(
        f"/v1/notes/{jot_id2}/route-auto",
        headers=auth_headers,
    )
    assert auto_resp.status_code == 200, auto_resp.json()
