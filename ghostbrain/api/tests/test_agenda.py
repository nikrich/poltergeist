"""GET /v1/agenda."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_note


def test_no_events_returns_empty(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_lists_today_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(
        tmp_vault,
        "20-contexts/work/calendar/2026-05-11-1100-design-crit.md",
        """---
title: Design crit · onboarding v3
date: 2026-05-11
time: "11:00"
duration: "30m"
with: [mira, jules, sam]
---
""",
    )
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    item = data[0]
    assert item["title"] == "Design crit · onboarding v3"
    assert item["time"] == "11:00"
    assert item["with"] == ["mira", "jules", "sam"]
    assert item["status"] == "upcoming"


def test_status_recorded_when_meeting_exists(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "20-contexts/work/calendar/2026-05-11-0900-standup.md", """---
title: standup
date: 2026-05-11
time: "09:00"
duration: "20m"
with: [team]
---
""")
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-11-standup.md", """---
title: standup
date: 2026-05-11
dur: "18:32"
speakers: 5
tags: []
---
""")
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    items = res.json()
    standup = next(i for i in items if i["title"] == "standup")
    assert standup["status"] == "recorded"
