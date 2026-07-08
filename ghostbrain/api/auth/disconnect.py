from __future__ import annotations

from ghostbrain.paths import state_dir


def _rm(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def disconnect(connector_id: str, account: str | None) -> None:
    d = state_dir()
    if connector_id == "gmail" and account:
        from ghostbrain.connectors.gmail.auth import token_path
        _rm(token_path(account))
    elif connector_id == "calendar" and account:
        from ghostbrain.connectors.calendar.google.auth import token_path
        _rm(token_path(account))
    elif connector_id == "slack":
        if account:
            from ghostbrain.connectors.slack.auth import token_path
            _rm(token_path(account))
        else:
            for f in d.glob("slack.*.token"):
                _rm(f)
    elif connector_id == "joplin":
        from ghostbrain.api.repo.routing import remove_routing_path
        remove_routing_path("joplin.token")
    elif connector_id in ("jira", "confluence"):
        # Shared Atlassian identity — only remove the routing subtree for this app,
        # leave the shared .env token (the other app may still use it).
        from ghostbrain.api.repo.routing import remove_routing_path
        remove_routing_path(f"{connector_id}.sites")
    elif connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        from ghostbrain.connectors.microsoft.graph.auth import cache_location
        _rm(cache_location())
    elif connector_id == "claude_code":
        import json
        from pathlib import Path
        p = Path.home() / ".claude" / "settings.json"
        if p.exists():
            try:
                doc = json.loads(p.read_text())
                # Guard: if parsed JSON is not a dict, skip processing
                if not isinstance(doc, dict):
                    return
                # Guard: ensure hooks is a dict before popping
                hooks = doc.get("hooks")
                if isinstance(hooks, dict):
                    hooks.pop("SessionEnd", None)
                    p.write_text(json.dumps(doc, indent=2))
            except (OSError, ValueError, AttributeError, TypeError):
                pass
    # github: nothing we own (gh manages its own login); no-op.
