"""Heatmap aggregation + per-day listing in the activity repo.

All tests write fixture jsonl files into the tmp vault's audit dir
(tmp_vault fixture from conftest creates 90-meta/audit/ and sets VAULT_PATH).
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.api.repo.activity import build_heatmap, list_activity_for_date


def _write_lines(vault: Path, date_iso: str, lines: list[str]) -> None:
    audit = vault / "90-meta" / "audit"
    (audit / f"{date_iso}.jsonl").write_text("\n".join(lines) + "\n")


def _event(date_iso: str, **fields) -> str:
    record = {"ts": f"{date_iso}T10:00:00+00:00", "event_type": "event_processed"}
    record.update(fields)
    return json.dumps(record)


def test_heatmap_counts_multiple_days_with_by_source(tmp_vault: Path):
    today = datetime.now(timezone.utc).date()
    d1 = (today - timedelta(days=1)).isoformat()
    d2 = (today - timedelta(days=3)).isoformat()
    _write_lines(tmp_vault, d1, [
        _event(d1, source="gmail"),
        _event(d1, source="gmail"),
        _event(d1, source="slack"),
    ])
    _write_lines(tmp_vault, d2, [_event(d2, source="gmail")])
    result = build_heatmap(days=365)
    assert result["total"] == 4
    assert result["maxCount"] == 3
    by_date = {d["date"]: d for d in result["days"]}
    assert by_date[d1]["count"] == 3
    assert by_date[d1]["bySource"] == {"gmail": 2, "slack": 1}
    assert by_date[d2]["count"] == 1
    # days come back ascending by date (sorted glob over the filenames)
    assert [d["date"] for d in result["days"]] == [d2, d1]


def test_heatmap_buckets_digest_and_sourceless_events(tmp_vault: Path):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, [
        _event(today, event_type="digest_generated"),
        _event(today, event_type="connector_skipped", event_id="joplin"),
        _event(today, source="jira"),
    ])
    result = build_heatmap(days=7)
    assert len(result["days"]) == 1
    assert result["days"][0]["bySource"] == {"digest": 1, "system": 1, "jira": 1}


def test_heatmap_skips_malformed_lines_with_warning(tmp_vault: Path, caplog):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, [
        _event(today, source="gmail"),
        "{ this is not json",
        _event(today, source="gmail"),
    ])
    with caplog.at_level(logging.WARNING, logger="ghostbrain.api.repo.activity"):
        result = build_heatmap(days=7)
    assert result["days"][0]["count"] == 2
    assert any("malformed audit line" in r.getMessage() for r in caplog.records)


def test_heatmap_excludes_files_outside_range(tmp_vault: Path):
    today = datetime.now(timezone.utc).date()
    inside = (today - timedelta(days=6)).isoformat()
    outside = (today - timedelta(days=7)).isoformat()
    _write_lines(tmp_vault, inside, [_event(inside, source="gmail")])
    _write_lines(tmp_vault, outside, [_event(outside, source="gmail")])
    # days=7 → window is [today-6 .. today]
    result = build_heatmap(days=7)
    assert [d["date"] for d in result["days"]] == [inside]


def test_heatmap_empty_audit_dir(tmp_vault: Path):
    assert build_heatmap(days=365) == {"days": [], "total": 0, "maxCount": 0}


def test_heatmap_omits_day_whose_file_has_no_valid_events(tmp_vault: Path):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, ["not json at all"])
    result = build_heatmap(days=7)
    assert result["days"] == []
    assert result["maxCount"] == 0


def test_heatmap_ignores_non_date_filenames(tmp_vault: Path):
    audit = tmp_vault / "90-meta" / "audit"
    (audit / "README.jsonl").write_text("{}\n")
    assert build_heatmap(days=7)["days"] == []


def test_list_for_date_returns_all_rows_newest_first(tmp_vault: Path):
    _write_lines(tmp_vault, "2026-06-04", [
        json.dumps({
            "ts": "2026-06-04T08:00:00+00:00",
            "event_type": "event_processed",
            "event_id": "evt-a",
            "source": "gmail",
            "inbox_path": "/v/00-inbox/raw/gmail/20260604T080000-morning-mail.md",
        }),
        json.dumps({
            "ts": "2026-06-04T17:00:00+00:00",
            "event_type": "digest_generated",
            "event_id": "2026-06-04",
            "path": "/v/10-daily/2026-06-04.md",
        }),
    ])
    rows = list_activity_for_date(date(2026, 6, 4))
    # ids are synthesized per line (event_id repeats within a day in real
    # audit logs, and the renderer keys rows by id) — newest first.
    assert [r["id"] for r in rows] == ["audit-2026-06-04-1", "audit-2026-06-04-0"]
    assert rows[0]["source"] == "digest"
    assert rows[0]["verb"] == "wrote digest"
    assert rows[1]["source"] == "gmail"
    assert rows[1]["subject"] == "morning-mail"
    assert rows[1]["at"] == "2026-06-04T08:00:00+00:00"


def test_list_for_date_missing_file_returns_empty(tmp_vault: Path):
    assert list_activity_for_date(date(1999, 1, 1)) == []
