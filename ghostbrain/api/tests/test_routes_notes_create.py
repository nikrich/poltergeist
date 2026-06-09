"""POST /v1/notes — create a jot and route synchronously."""
import frontmatter

from ghostbrain.worker.router import RoutingDecision


def test_post_notes_writes_routes_and_returns_routed(
    tmp_vault, client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="sanlam",
            confidence=0.82,
            reasoning="matches sanlam",
            method="llm",
            secondary_contexts=[],
        ),
    )
    (tmp_vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)
    resp = client.post(
        "/v1/notes", json={"body": "ascp wizard idea"}, headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "routed"
    assert data["path"].startswith("20-contexts/sanlam/notes/")
    fm = frontmatter.load(tmp_vault / data["path"])
    assert fm["context"] == "sanlam"
    assert fm["routingMethod"] == "llm"


def test_post_notes_low_confidence_falls_back_to_manual_review(
    tmp_vault, client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="needs_review",
            confidence=0.0,
            reasoning="no classifiable content",
            method="fallback",
            secondary_contexts=[],
        ),
    )
    resp = client.post("/v1/notes", json={"body": "..."}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "manual_review"
    assert data["path"].startswith("00-inbox/raw/manual/")


def test_post_notes_router_exception_falls_back_to_manual_review(
    tmp_vault, client, auth_headers, monkeypatch
):
    def boom(event, **kw):
        raise RuntimeError("LLM timeout")

    monkeypatch.setattr("ghostbrain.api.repo.notes_manual.route_event", boom)
    resp = client.post("/v1/notes", json={"body": "anything"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "manual_review"


def test_post_notes_empty_body_rejected(tmp_vault, client, auth_headers):
    resp = client.post("/v1/notes", json={"body": ""}, headers=auth_headers)
    assert resp.status_code == 422


def test_post_notes_whitespace_only_body_rejected(tmp_vault, client, auth_headers):
    resp = client.post("/v1/notes", json={"body": "   "}, headers=auth_headers)
    assert resp.status_code == 422


def test_post_notes_valid_captured_at_stamps_created_and_id(
    tmp_vault, client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="needs_review",
            confidence=0.0,
            reasoning="no classifiable content",
            method="fallback",
            secondary_contexts=[],
        ),
    )
    resp = client.post(
        "/v1/notes",
        json={"body": "timestamped jot", "capturedAt": "2026-05-14T09:30:15+00:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"].startswith("manual-20260514T093015")
    fm = frontmatter.load(tmp_vault / data["path"])
    assert fm["created"] == "2026-05-14T09:30:15+00:00"


def test_post_notes_naive_captured_at_rejected(tmp_vault, client, auth_headers):
    resp = client.post(
        "/v1/notes",
        json={"body": "has a timestamp", "capturedAt": "2026-05-14T09:30:15"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
