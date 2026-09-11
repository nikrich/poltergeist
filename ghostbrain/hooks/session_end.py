"""`ghostbrain-api session-end` — Claude Code SessionEnd hook.

Python port of orchestration/hooks/session-end.sh so the packaged app needs no
extra script on disk. Reads the hook payload from stdin, snapshots the
transcript (Claude Code prunes the original), and queues an event for the
worker. Always exits 0: a hook failure must never break Claude Code.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from ghostbrain.paths import vault_path


def handle(payload: dict, *, vault: Path, now: datetime) -> Path | None:
    session_id = str(payload.get("session_id") or "")
    reason = str(payload.get("reason") or "")
    if not session_id:
        print("session-end: missing session_id; skipping", file=sys.stderr)
        return None
    if reason == "resume":
        print("session-end: reason=resume, skipping", file=sys.stderr)
        return None

    transcript = str(payload.get("transcript_path") or "")
    cwd = str(payload.get("cwd") or "")
    queue_dir = vault / "90-meta" / "queue" / "pending"
    transcripts_dir = vault / "90-meta" / "queue" / "transcripts"
    queue_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    snapshot: str | None = None
    if transcript and Path(transcript).is_file():
        target = transcripts_dir / f"{session_id}.jsonl"
        try:
            shutil.copyfile(transcript, target)
            snapshot = str(target)
        except OSError:
            snapshot = None

    ts = now.astimezone(UTC)
    out = queue_dir / f"{ts.strftime('%Y%m%dT%H%M%SZ')}-claude-code-{session_id}.json"
    event = {
        "id": f"claudecode-{session_id}",
        "source": "claude-code",
        "type": "session",
        "subtype": reason or "ended",
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": f"Claude Code session {session_id[:8]}",
        "rawData": {
            "session_id": session_id,
            "transcript_path": transcript,
            "transcript_snapshot": snapshot,
            "cwd": cwd,
            "reason": reason,
        },
        "metadata": {
            "projectPath": cwd,
            "sessionId": session_id,
            "transcriptPath": snapshot or transcript,
        },
    }
    out.write_text(json.dumps(event, indent=2), encoding="utf-8")
    print(f"session-end: queued {out} (snapshot={snapshot or 'none'})", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError("payload is not an object")
    except (TypeError, ValueError, OSError) as e:
        print(f"session-end: unreadable payload ({e}); skipping", file=sys.stderr)
        return 0
    try:
        handle(payload, vault=vault_path(), now=datetime.now(UTC))
    except Exception as e:  # noqa: BLE001 — never fail the editor's hook
        print(f"session-end: failed ({e}); skipping", file=sys.stderr)
    return 0
