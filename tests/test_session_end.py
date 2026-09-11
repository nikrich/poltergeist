from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.hooks import session_end

NOW = datetime(2026, 9, 11, 8, 30, 5, tzinfo=timezone.utc)


def test_queues_event_and_snapshots_transcript(tmp_path: Path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"a":1}\n')
    vault = tmp_path / "vault"
    out = session_end.handle(
        {"session_id": "abcdef12-3456", "transcript_path": str(transcript), "cwd": "/proj", "reason": "exit"},
        vault=vault, now=NOW,
    )
    assert out == vault / "90-meta" / "queue" / "pending" / "20260911T083005Z-claude-code-abcdef12-3456.json"
    snap = vault / "90-meta" / "queue" / "transcripts" / "abcdef12-3456.jsonl"
    assert snap.read_text() == '{"a":1}\n'
    event = json.loads(out.read_text())
    assert event == {
        "id": "claudecode-abcdef12-3456",
        "source": "claude-code",
        "type": "session",
        "subtype": "exit",
        "timestamp": "2026-09-11T08:30:05Z",
        "title": "Claude Code session abcdef12",
        "rawData": {
            "session_id": "abcdef12-3456",
            "transcript_path": str(transcript),
            "transcript_snapshot": str(snap),
            "cwd": "/proj",
            "reason": "exit",
        },
        "metadata": {"projectPath": "/proj", "sessionId": "abcdef12-3456", "transcriptPath": str(snap)},
    }


def test_missing_transcript_still_queues_without_snapshot(tmp_path: Path):
    out = session_end.handle(
        {"session_id": "s1", "transcript_path": str(tmp_path / "nope.jsonl"), "cwd": "", "reason": ""},
        vault=tmp_path / "vault", now=NOW,
    )
    event = json.loads(out.read_text())
    assert event["subtype"] == "ended"
    assert event["rawData"]["transcript_snapshot"] is None
    assert event["metadata"]["transcriptPath"] == str(tmp_path / "nope.jsonl")


def test_resume_and_missing_session_id_are_skipped(tmp_path: Path):
    assert session_end.handle({"session_id": "s1", "reason": "resume"}, vault=tmp_path, now=NOW) is None
    assert session_end.handle({"reason": "exit"}, vault=tmp_path, now=NOW) is None
    assert not (tmp_path / "90-meta").exists() or not list((tmp_path / "90-meta").rglob("*.json"))


def test_main_reads_stdin_and_honors_vault_path(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "v"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "zz", "reason": "exit"})))
    assert session_end.main([]) == 0
    assert list((tmp_path / "v" / "90-meta" / "queue" / "pending").glob("*-claude-code-zz.json"))
    assert "queued" in capsys.readouterr().err


def test_main_with_garbage_stdin_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert session_end.main([]) == 0
    assert "skipping" in capsys.readouterr().err


def test_session_end_is_registered_subcommand():
    from ghostbrain.api.__main__ import SUBCOMMANDS

    assert SUBCOMMANDS["session-end"] == "ghostbrain.hooks.session_end:main"
