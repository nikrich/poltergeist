"""Tests for the Joplin connector. The Joplin Data API HTTP calls are mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


def _ts_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


_FOLDERS_PAGE = {
    "items": [
        {"id": "fold-sanlam", "parent_id": "", "title": "Sanlam"},
        {"id": "fold-personal", "parent_id": "", "title": "Personal"},
    ],
    "has_more": False,
}

_NOTES_PAGE = {
    "items": [
        {
            "id": "note-a",
            "parent_id": "fold-sanlam",
            "title": "Compliance follow-up",
            "body": "Need to ping legal about the audit.",
            "created_time": _ts_ms(2026, 5, 10),
            "updated_time": _ts_ms(2026, 5, 14),
            "is_todo": 0,
            "todo_completed": 0,
            "markup_language": 1,
            "source_url": "",
        },
        {
            "id": "note-b",
            "parent_id": "fold-personal",
            "title": "Buy milk",
            "body": "and eggs",
            "created_time": _ts_ms(2026, 5, 12),
            "updated_time": _ts_ms(2026, 5, 13),
            "is_todo": 1,
            "todo_completed": 0,
            "markup_language": 1,
            "source_url": "",
        },
        {
            "id": "note-stale",
            "parent_id": "fold-sanlam",
            "title": "Old note",
            "body": "ancient history",
            "created_time": _ts_ms(2026, 1, 1),
            "updated_time": _ts_ms(2026, 1, 1),
            "is_todo": 0,
            "todo_completed": 0,
            "markup_language": 1,
            "source_url": "",
        },
    ],
    "has_more": False,
}

_EMPTY_PAGE = {"items": [], "has_more": False}


def _make_connector(tmp_path: Path, *, notebooks: dict | None = None):
    from ghostbrain.connectors.joplin import JoplinConnector

    return JoplinConnector(
        config={
            "token": "test-token",
            "host": "http://localhost:41184",
            "notebooks": notebooks or {},
        },
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )


def _fake_get_json_factory(folder_page, notes_pages):
    """Returns a _get_json replacement that serves folders + paged notes."""
    note_iter = iter(notes_pages)

    def _fake(url: str):
        if "/folders" in url:
            return folder_page
        if "/notes" in url:
            try:
                return next(note_iter)
            except StopIteration:
                return _EMPTY_PAGE
        return {}

    return _fake


def test_fetch_returns_normalized_events(vault: Path, tmp_path: Path) -> None:
    connector = _make_connector(tmp_path)

    fake = _fake_get_json_factory(_FOLDERS_PAGE, [_NOTES_PAGE])
    with patch.object(connector, "_get_json", side_effect=fake):
        events = connector.fetch(datetime(2026, 5, 8, tzinfo=timezone.utc))

    # `note-stale` is older than `since`, but the DESC walk only stops once
    # an older note is seen; the two newer notes come through.
    ids = {e["id"] for e in events}
    assert ids == {"joplin:note:note-a", "joplin:note:note-b"}

    by_id = {e["id"]: e for e in events}
    a = by_id["joplin:note:note-a"]
    assert a["source"] == "joplin"
    assert a["type"] == "note"
    assert a["subtype"] == "note"
    assert a["title"] == "Compliance follow-up"
    assert a["metadata"]["notebook"] == "Sanlam"
    assert a["metadata"]["notebookId"] == "fold-sanlam"
    # rawData should not duplicate the body — it's already in `body`.
    assert "body" not in a["rawData"]

    b = by_id["joplin:note:note-b"]
    assert b["subtype"] == "todo"
    assert b["metadata"]["isTodo"] is True
    assert b["metadata"]["todoCompleted"] is False


def test_notebook_allowlist_filters_out_unlisted(vault: Path, tmp_path: Path) -> None:
    connector = _make_connector(tmp_path, notebooks={"Sanlam": "sanlam"})

    fake = _fake_get_json_factory(_FOLDERS_PAGE, [_NOTES_PAGE])
    with patch.object(connector, "_get_json", side_effect=fake):
        events = connector.fetch(datetime(2026, 5, 8, tzinfo=timezone.utc))

    # Personal note dropped; Sanlam note kept.
    assert {e["id"] for e in events} == {"joplin:note:note-a"}


def test_empty_body_notes_skipped(vault: Path, tmp_path: Path) -> None:
    connector = _make_connector(tmp_path)

    notes = {
        "items": [
            {
                "id": "title-only",
                "parent_id": "fold-sanlam",
                "title": "Just a title, no body",
                "body": "   ",
                "created_time": _ts_ms(2026, 5, 14),
                "updated_time": _ts_ms(2026, 5, 14),
                "is_todo": 0,
                "todo_completed": 0,
                "markup_language": 1,
                "source_url": "",
            },
        ],
        "has_more": False,
    }
    fake = _fake_get_json_factory(_FOLDERS_PAGE, [notes])
    with patch.object(connector, "_get_json", side_effect=fake):
        events = connector.fetch(datetime(2026, 5, 8, tzinfo=timezone.utc))

    assert events == []


def test_first_run_caps_lookback_to_seven_days(vault: Path, tmp_path: Path) -> None:
    connector = _make_connector(tmp_path)

    # Very old `since` (the default when last_run state is missing).
    fake = _fake_get_json_factory(_FOLDERS_PAGE, [_NOTES_PAGE])
    with patch.object(connector, "_get_json", side_effect=fake):
        # `note-stale` is dated 2026-01-01; even with `since=1970` the
        # 7-day floor should mean we walk only recent notes. The DESC
        # iterator breaks on the stale note → fewer than 3 events.
        events = connector.fetch(datetime(1970, 1, 1, tzinfo=timezone.utc))

    assert all(e["id"] != "joplin:note:note-stale" for e in events)


def test_constructor_requires_token(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.joplin import JoplinConnector

    with pytest.raises(RuntimeError, match="joplin.token"):
        JoplinConnector(
            config={"token": ""},
            queue_dir=tmp_path / "q",
            state_dir=tmp_path / "s",
        )


def test_health_check_passes_when_ping_returns_clipper_text(
    vault: Path, tmp_path: Path
) -> None:
    connector = _make_connector(tmp_path)

    class _Resp:
        status_code = 200
        text = "JoplinClipperServer"

    with patch.object(connector._session, "get", return_value=_Resp()):
        assert connector.health_check() is True


def test_health_check_fails_on_wrong_body(vault: Path, tmp_path: Path) -> None:
    connector = _make_connector(tmp_path)

    class _Resp:
        status_code = 200
        text = "something else"

    with patch.object(connector._session, "get", return_value=_Resp()):
        assert connector.health_check() is False


def test_router_fast_routes_by_notebook(vault: Path) -> None:
    from ghostbrain.worker.router import route_event

    event = {
        "id": "joplin:note:abc",
        "source": "joplin",
        "title": "x",
        "body": "y",
        "metadata": {"notebook": "Sanlam"},
    }
    routing = {"joplin": {"notebooks": {"Sanlam": "sanlam"}}}

    decision = route_event(event, content_excerpt="x y", routing=routing, config={})
    assert decision.context == "sanlam"
    assert decision.method == "path"
    assert decision.confidence == 1.0
