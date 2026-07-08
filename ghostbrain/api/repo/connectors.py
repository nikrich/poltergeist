"""Connector enumeration and state."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.paths import state_dir

# Static display metadata. Adding a new connector requires adding here too —
# small explicit dev tax in exchange for clean display names.
_DISPLAY: dict[str, dict] = {
    "claude_code": {
        "displayName": "Claude Code",
        "scopes": ["read .claude/projects"],
        "pulls": ["sessions", "tool uses"],
        "vaultDestination": "20-contexts/{ctx}/claude_code/",
    },
    "github": {
        "displayName": "github",
        "scopes": ["repo:read"],
        "pulls": ["issues", "PRs", "commits"],
        "vaultDestination": "20-contexts/{ctx}/github/",
    },
    "jira": {
        "displayName": "jira",
        "scopes": ["read:jira-work"],
        "pulls": ["issues", "comments"],
        "vaultDestination": "20-contexts/{ctx}/jira/",
    },
    "confluence": {
        "displayName": "confluence",
        "scopes": ["read:confluence-content"],
        "pulls": ["pages", "comments"],
        "vaultDestination": "20-contexts/{ctx}/confluence/",
    },
    "calendar": {
        "displayName": "calendar",
        "scopes": ["read events"],
        "pulls": ["events", "attendees"],
        "vaultDestination": "20-contexts/{ctx}/calendar/",
    },
    "atlassian": {
        "displayName": "atlassian",
        "scopes": ["read profile"],
        "pulls": ["account info"],
        "vaultDestination": "20-contexts/{ctx}/atlassian/",
    },
    "slack": {
        "displayName": "slack",
        "scopes": ["channels:history", "users:read"],
        "pulls": ["mentions", "threads"],
        "vaultDestination": "20-contexts/{ctx}/slack/",
    },
    "joplin": {
        "displayName": "Joplin",
        "scopes": ["read notes"],
        "pulls": ["notes", "notebooks"],
        "vaultDestination": "20-contexts/{ctx}/joplin/",
    },
    "gmail": {
        "displayName": "gmail",
        "scopes": ["read messages", "read labels"],
        "pulls": ["threads", "attachments"],
        "vaultDestination": "20-contexts/{ctx}/gmail/",
    },
    "outlook_mail": {
        "displayName": "Outlook Mail",
        "scopes": ["Mail.Read"],
        "pulls": ["emails"],
        "vaultDestination": "20-contexts/{ctx}/outlook_mail/",
    },
    "teams_chat": {
        "displayName": "Teams Chat",
        "scopes": ["Chat.Read"],
        "pulls": ["messages"],
        "vaultDestination": "20-contexts/{ctx}/teams_chat/",
    },
    "teams_meetings": {
        "displayName": "Teams Meetings",
        "scopes": ["OnlineMeetingTranscript.Read.All"],
        "pulls": ["transcripts"],
        "vaultDestination": "20-contexts/{ctx}/teams_meetings/",
    },
}

# Connector id → state-file key. Most connectors use their id; one exception:
# the calendar connector writes state to macos_calendar.last_run.
_STATE_KEY: dict[str, str] = {
    "calendar": "macos_calendar",
}

# Directories under ghostbrain/connectors/ that look like connectors but
# aren't — shared infrastructure modules (e.g. atlassian provides shared
# Cloud API helpers used by jira + confluence; it has no fetcher of its own).
_HIDDEN: frozenset[str] = frozenset({"atlassian"})

# Connector id → inbox subdirectory name under 00-inbox/raw/. Most match;
# claude_code is captured by the worker as claude-code (hyphenated).
_INBOX_DIR: dict[str, str] = {
    "claude_code": "claude-code",
}

# Connector id → per-context subdirectory name under 20-contexts/<ctx>/.
# Most connector ids match the directory verbatim; claude_code captures
# land under `claude/` (chosen for readability over the underscore form).
_CONTEXT_DIR: dict[str, str] = {
    "claude_code": "claude",
}


def _list_connector_ids() -> list[str]:
    """Connector IDs we ship, minus any hidden infrastructure-only ones.

    Sourced from the static `_DISPLAY` dict so this works the same way in
    development (source tree on disk) and packaged builds (PyInstaller-frozen
    bundle, where filesystem-scanning `ghostbrain/connectors/` finds nothing
    because PyInstaller doesn't preserve the source-layout package
    directories for runtime introspection).
    """
    return sorted(cid for cid in _DISPLAY if cid not in _HIDDEN)


def _has_inbox_captures(connector_id: str) -> bool:
    """Some connectors (e.g. claude_code) are event-driven, not polling —
    they never write a .last_run file, but their captures land in the inbox
    just the same. Treat presence of inbox files as evidence of liveness."""
    from ghostbrain.paths import vault_path

    dir_name = _INBOX_DIR.get(connector_id, connector_id)
    inbox = vault_path() / "00-inbox" / "raw" / dir_name
    if not inbox.exists():
        return False
    return any(inbox.glob("*.md"))


def _count_indexed(connector_id: str) -> int:
    """Count .md files this connector has produced across the vault.

    Looks in two places:
      ``00-inbox/raw/<inbox-dir>/`` — captures awaiting routing
      ``20-contexts/*/<connector-dir>/**`` — already-routed captures

    Most connectors use ``connector_id`` as both directory names; the
    `_INBOX_DIR` map handles the few that differ (``claude_code`` is
    written as ``claude-code/`` by the worker).

    The connectors detail panel shows this as "indexed items" — without
    it the panel reads 0 even when the vault has dozens of captures, so
    users assume a connector is broken when it's actually fine.
    """
    from ghostbrain.paths import vault_path

    root = vault_path()
    inbox_dir = _INBOX_DIR.get(connector_id, connector_id)
    ctx_subdir = _CONTEXT_DIR.get(connector_id, connector_id)

    n = 0
    inbox = root / "00-inbox" / "raw" / inbox_dir
    if inbox.exists():
        n += sum(1 for _ in inbox.glob("*.md"))

    contexts = root / "20-contexts"
    if contexts.exists():
        # 20-contexts/<ctx>/<ctx_subdir>/**/*.md — rglob so nested
        # subdirectories (github/prs, calendar/transcripts) are counted.
        for ctx_dir in contexts.iterdir():
            if not ctx_dir.is_dir():
                continue
            conn_dir = ctx_dir / ctx_subdir
            if conn_dir.exists():
                n += sum(1 for _ in conn_dir.rglob("*.md"))
    return n


def _read_last_run(connector_id: str) -> str | None:
    """Read the .last_run file content (ISO timestamp string) or None."""
    key = _STATE_KEY.get(connector_id, connector_id)
    f = state_dir() / f"{key}.last_run"
    if not f.exists():
        return None
    try:
        return f.read_text().strip()
    except OSError:
        return None


def _connector_record(connector_id: str) -> dict:
    display = _DISPLAY.get(connector_id, {
        "displayName": connector_id,
        "scopes": [],
        "pulls": [],
        "vaultDestination": f"20-contexts/{{ctx}}/{connector_id}/",
    })
    # A connector is 'on' if EITHER:
    #   - it has a .last_run file (polling connector that has run successfully), or
    #   - it has captures already in the inbox (event-driven connector like claude_code).
    # Either signal means the connector is configured and producing data. Recency
    # surfaces via lastSyncAt; the UI flags stale runs there.
    last_run = _read_last_run(connector_id)
    has_inbox = _has_inbox_captures(connector_id)
    run_state = "on" if (last_run or has_inbox) else "off"
    return {
        "id": connector_id,
        "displayName": display["displayName"],
        "state": run_state,
        "count": _count_indexed(connector_id),
        "lastSyncAt": last_run,
        "account": None,
        "throughput": None,
        "error": None,
    }


def list_connectors() -> list[dict]:
    return [_connector_record(cid) for cid in _list_connector_ids()]


def get_connector(connector_id: str) -> dict | None:
    if connector_id not in _list_connector_ids():
        return None
    base = _connector_record(connector_id)
    display = _DISPLAY.get(connector_id, {})
    return {
        **base,
        "scopes": display.get("scopes", []),
        "pulls": display.get("pulls", []),
        "vaultDestination": display.get("vaultDestination", f"20-contexts/{{ctx}}/{connector_id}/"),
    }
