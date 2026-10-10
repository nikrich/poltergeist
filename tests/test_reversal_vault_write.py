"""B4: decision reversals write through the vault write path as worker:reversal."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.llm.client import LLMResult
from ghostbrain.vault_write import set_hold_policy

DECISIONS = "20-contexts/work/calendar/artifacts/decisions"
NOW = datetime.now(timezone.utc)
RULING = [{"contradicts_id": "old-1", "reasoning": "earlier said DynamoDB; new picks Postgres"}]


def _llm(payload: dict) -> LLMResult:
    return LLMResult(text=json.dumps(payload), structured=None, model="haiku", cost_usd=0.0,
                     duration_ms=1, session_id="s", raw={})


def _decision(vault: Path, artifact_id: str, title: str, created: datetime, *, extra: str = "") -> Path:
    path = vault / DECISIONS / f"{artifact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {artifact_id}\n"
        "context: work\n"
        "type: artifact\n"
        "artifactType: decision\n"
        f"created: '{created.isoformat()}'\n"
        f'title: "{title}"   # from the recorder\n'
        "tags: [db, infra]\n"
        f"{extra}"
        "---\n\n"
        f"# {title}\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def _dump(fields: dict) -> str:
    return yaml.safe_dump(fields, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _run(new_path: Path, reversals: list[dict]):
    from ghostbrain.worker import reversal

    with patch("ghostbrain.worker.reversal.llm.run", return_value=_llm({"reversals": reversals})):
        return reversal.check_for_reversals(new_path)


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_hold_policy(None)


def test_only_the_link_lines_are_added(vault: Path) -> None:
    from ghostbrain.worker import reversal

    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10),
                    extra="updated: 2026-01-02\n")
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    old_before, new_before = old.read_text(), new.read_text()
    result = _run(new, RULING)
    assert result.contradicted_paths == [old]
    old_link, new_link = reversal._wikilink_for(old), reversal._wikilink_for(new)
    assert old.read_text() == old_before.replace(
        "---\n\n#", _dump({"reversed_by": [new_link]}) + "---\n\n#", 1)
    assert new.read_text() == new_before.replace(
        "---\n\n#",
        _dump({"contradicts": [old_link], "reversalReasons": [RULING[0]["reasoning"]]}) + "---\n\n#",
        1,
    )


def test_reversal_changes_are_listed_and_snapshotted(vault: Path) -> None:
    _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    _run(new, RULING)
    rows = changes.list_changes(actor="worker:reversal")
    assert sorted(r.rel_path for r in rows) == [f"{DECISIONS}/new-1.md", f"{DECISIONS}/old-1.md"]
    assert {r.op for r in rows} == {"modify"}
    assert all(store.list_snapshots(r.rel_path) for r in rows)


def test_an_existing_backlink_is_not_duplicated(vault: Path) -> None:
    from ghostbrain.worker import reversal

    new = _decision(vault, "new-1", "Use Postgres", NOW)
    link = reversal._wikilink_for(new)
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10),
                    extra=f"reversed_by:\n- '{link}'\n")
    before = old.read_bytes()
    _run(new, RULING)
    assert old.read_bytes() == before
    assert [r.rel_path for r in changes.list_changes(actor="worker:reversal")] == [
        f"{DECISIONS}/new-1.md"]


def test_a_held_link_writes_nothing(vault: Path) -> None:
    set_hold_policy(lambda _p: ["held for test"])
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    before = (old.read_bytes(), new.read_bytes())
    result = _run(new, RULING)
    assert result.contradicted_paths == [old]
    assert (old.read_bytes(), new.read_bytes()) == before
    assert len(changes.list_changes(status="pending")) == 2


def test_a_history_failure_is_logged_not_raised(vault: Path, monkeypatch) -> None:
    from ghostbrain.vault_write import HistoryUnavailable, writer

    def boom(*_a, **_k):
        raise HistoryUnavailable("history unavailable: disk full")

    monkeypatch.setattr(writer, "_snapshot", boom)
    old = _decision(vault, "old-1", "Use DynamoDB", NOW - timedelta(days=10))
    new = _decision(vault, "new-1", "Use Postgres", NOW)
    before = (old.read_bytes(), new.read_bytes())
    result = _run(new, RULING)
    assert result.contradicted_paths == []
    assert (old.read_bytes(), new.read_bytes()) == before
