from __future__ import annotations

import logging

from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.api.auth.disconnect")


def _rm(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _safe_account(account: str | None) -> str | None:
    """Guard against path-manipulating account values.

    Returns None if account is None/empty, or contains any of: "/", "\\", "..", "\x00".
    Otherwise returns account unchanged.
    """
    if not account or not account.strip():
        return None
    if "/" in account or "\\" in account or ".." in account or "\x00" in account:
        return None
    return account


def disconnect(connector_id: str, account: str | None) -> None:
    d = state_dir()

    # Record if a raw account was provided before sanitizing.
    raw_account_provided = bool(account and account.strip())
    # Sanitize account to reject path-manipulating values.
    account = _safe_account(account)

    if connector_id == "gmail" and account:
        from ghostbrain.connectors.gmail.auth import token_path
        _rm(token_path(account))
    elif connector_id == "gdrive" and account:
        from ghostbrain.connectors.gdrive.auth import token_path
        _rm(token_path(account))
    elif connector_id == "calendar" and account:
        from ghostbrain.connectors.calendar.google.auth import token_path
        _rm(token_path(account))
    elif connector_id == "slack":
        if account:
            from ghostbrain.connectors.slack.auth import token_path
            _rm(token_path(account))
        elif not raw_account_provided:
            # Only delete all slack tokens if no account was provided at all.
            # If a raw account was provided but got sanitized to None, skip.
            for f in d.glob("slack.*.token"):
                _rm(f)
    elif connector_id == "joplin":
        from ghostbrain.api.repo.routing import remove_routing_path
        remove_routing_path("joplin.token")
    elif connector_id in ("jira", "confluence"):
        # Shared Atlassian identity — only remove the site's shared token when
        # the other app (jira/confluence) no longer has an account for it too.
        if account:
            from ghostbrain.connectors.atlassian._base import token_path
            other = "confluence" if connector_id == "jira" else "jira"
            from ghostbrain import accounts as _acc
            if _acc.get_account(other, account) is None:
                _rm(token_path(account))  # only when the other app doesn't use this site
    elif connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        from ghostbrain.connectors.microsoft.graph import auth as ms_auth
        if account:
            from ghostbrain.api.repo.routing import load_routing
            try:
                ms_auth.remove_cached_account(load_routing().get("microsoft") or {}, account)
            except Exception as e:  # noqa: BLE001 — best effort; the registry entry still goes
                log.warning("could not remove cached Microsoft account %s: %s", account, e)
        else:
            _rm(ms_auth.cache_location())
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

    from ghostbrain import accounts
    acct_connector = accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(connector_id)
    if acct_connector and account:
        accounts.remove_account(acct_connector, account)
