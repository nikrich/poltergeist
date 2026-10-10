"""GET /v1/meetings."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_note


MEETING_FRONTMATTER = """---
title: design crit · onboarding v3
date: 2026-05-08
dur: "28:14"
speakers: 4
tags: [design]
---

# Transcript
mira: okay so the onboarding flow...
"""


def test_empty_returns_no_meetings(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/meetings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"total": 0, "items": []}


def test_meetings_are_listed(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(
        tmp_vault,
        "20-contexts/work/meetings/2026-05-08-design-crit.md",
        MEETING_FRONTMATTER,
    )
    res = client.get("/v1/meetings", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["title"] == "design crit · onboarding v3"
    assert item["date"] == "2026-05-08"
    assert item["dur"] == "28:14"
    assert item["speakers"] == 4
    assert "design" in item["tags"]


def test_meetings_sorted_by_date_desc(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-01.md",
        '---\ntitle: old\ndate: 2026-05-01\ndur: "1:00"\nspeakers: 2\ntags: []\n---\n')
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-08.md",
        '---\ntitle: new\ndate: 2026-05-08\ndur: "1:00"\nspeakers: 2\ntags: []\n---\n')
    res = client.get("/v1/meetings", headers=auth_headers)
    items = res.json()["items"]
    assert items[0]["date"] == "2026-05-08"
    assert items[1]["date"] == "2026-05-01"


def test_same_day_meetings_sorted_by_time_desc(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path,
):
    d = tmp_vault / "20-contexts" / "work" / "calendar" / "transcripts"
    d.mkdir(parents=True)
    (d / "standup.md").write_text(
        "---\ntitle: standup\nstarted: '2026-09-14T07:00:00+00:00'\ndurationSeconds: 900\n---\nbody\n"
    )
    (d / "weekly-sync.md").write_text(
        "---\ntitle: Weekly sync\nstarted: '2026-09-14T08:29:47+00:00'\ndurationSeconds: 1448\n---\nbody\n"
    )
    (d / "old.md").write_text(
        "---\ntitle: yesterday\nstarted: '2026-09-13T15:00:00+00:00'\ndurationSeconds: 600\n---\nbody\n"
    )
    (d / "dateonly.md").write_text(
        '---\ntitle: date only\ndate: 2026-09-14\ndur: "0:10"\nspeakers: 1\ntags: []\n---\n'
    )
    res = client.get("/v1/meetings", headers=auth_headers)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [m["title"] for m in items] == ["Weekly sync", "standup", "date only", "yesterday"]
    assert items[0]["startedAt"].startswith("2026-09-14T")
    assert items[0]["time"] is not None and len(items[0]["time"]) == 5
    assert items[2]["time"] is None and items[2]["startedAt"] is None
