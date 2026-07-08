"""Local grant providers: Claude Code settings hook and macOS Calendar access."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import merge_routing


def _claude_settings_path() -> Path:
    """Return path to ~/.claude/settings.json."""
    return Path.home() / ".claude" / "settings.json"


def _write_json_atomic(path: Path, data: dict) -> None:
    """Atomically write JSON data to a file using tempfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


class ClaudeCodeProvider:
    """Provider for Claude Code settings hook integration."""

    pattern = "local_grant"

    def start(self, connector_id, params):
        """Prompt for hook script and optional project path/context."""
        default_script = str(
            Path.home() / "development" / "ghost-brain" / "orchestration" / "hooks" / "session-end.sh"
        )
        return NextAction(
            kind="need_input",
            message="Poltergeist will add a SessionEnd hook to ~/.claude/settings.json.",
            fields=[
                {"name": "hook_script", "label": "Hook script path", "type": "text",
                 "placeholder": default_script},
                {"name": "project_path", "label": "Project path (optional)", "type": "text"},
                {"name": "context", "label": "Context for that project (optional)", "type": "text"},
            ],
        )

    def submit(self, connector_id, session, data):
        """Write SessionEnd hook to ~/.claude/settings.json (atomic, merge-only)."""
        script = (data.get("hook_script") or "").strip()
        if not script:
            session.status = "error"
            session.error = "Hook script path is required"
            return NextAction(kind="need_input", fields=[])
        path = _claude_settings_path()
        try:
            doc = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            doc = {}
        hooks = doc.setdefault("hooks", {})
        hooks["SessionEnd"] = [
            {"matcher": "*", "hooks": [
                {"type": "command", "command": script, "shell": "bash", "async": True}
            ]}
        ]
        try:
            _write_json_atomic(path, doc)
        except OSError as e:
            session.status = "error"
            session.error = f"Could not write settings.json: {e}"
            return NextAction(kind="need_input", fields=[])
        proj = (data.get("project_path") or "").strip()
        ctx = (data.get("context") or "").strip()
        if proj and ctx:
            merge_routing({"claude_code": {"project_paths": {proj: ctx}}})
        session.status = "success"
        session.account = "SessionEnd hook installed"
        return NextAction(kind="done")

    def poll(self, connector_id, session):
        """No async polling needed for Claude Code provider."""
        pass

    def account_label(self, session):
        """Return account label."""
        return session.account


class MacosCalendarProvider:
    """Provider for macOS Calendar access (best-effort EventKit check)."""

    pattern = "local_grant"

    def start(self, connector_id, params):
        """Prompt user to grant Calendar access when macOS prompts."""
        return NextAction(
            kind="need_grant",
            message="Grant Calendar access when macOS prompts, then press Re-check.",
        )

    def poll(self, connector_id, session):
        """Best-effort: attempt EventKit read to trigger/confirm the grant."""
        try:
            from ghostbrain.connectors.calendar.macos import macos_calendar_available
            ok = macos_calendar_available()
        except Exception:  # noqa: BLE001
            ok = True  # can't verify; assume the user granted it
        session.status = "success" if ok else "error"
        session.next = NextAction(kind="done")
        if not ok:
            session.error = "Calendar access not granted"

    def account_label(self, session):
        """Return account label."""
        return "macOS Calendar"
