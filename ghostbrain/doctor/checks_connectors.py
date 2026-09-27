"""Connector, Claude Code hook, and CLI shim checks (Task 5)."""
from __future__ import annotations

import shutil

from ghostbrain.api import claude_settings
from ghostbrain.doctor import CheckResult, Fix, register

# Check order (also the order of `configured` in the result).
_ORDER = ("github", "gmail", "calendar", "slack", "jira", "confluence", "joplin", "claude_code")
# Connectors whose configuration is their accounts in 90-meta/accounts.yaml.
_ACCOUNT_BACKED = {"gmail": "gmail", "slack": "slack", "jira": "jira", "confluence": "confluence"}
# Connectors configured by a routing.yaml block: (top-level key, sub-key).
_BLOCKS: dict[str, tuple[str, str]] = {
    "github": ("github", "orgs"),
    "joplin": ("joplin", "token"),
    "claude_code": ("claude_code", "project_paths"),
}


def _routing() -> dict:
    from ghostbrain.api.repo.routing import load_routing

    return load_routing()


def _probe(connector_id: str):
    from ghostbrain.api.repo.connector_probe import probe

    return probe(connector_id)


def _account_ids(account_connector: str) -> list[str]:
    from ghostbrain import accounts

    return [a.id for a in accounts.list_accounts(account_connector)]


def _configured(cid: str, routing: dict) -> tuple[bool, bool]:
    """(has configuration, configuration is relevant for the on-but-empty check)."""
    if cid in _ACCOUNT_BACKED:
        return bool(_account_ids(_ACCOUNT_BACKED[cid])), True
    if cid == "calendar":
        macos = (((routing.get("calendar") or {}).get("macos") or {}).get("accounts")) or {}
        return bool(_account_ids("calendar_google") or macos), True
    key, sub = _BLOCKS[cid]
    return bool((routing.get(key) or {}).get(sub)), key in routing


@register("connectors")
def check_connectors() -> CheckResult:
    routing = _routing()
    configured: list[str] = []
    on_but_empty: list[str] = []
    for cid in _ORDER:
        has_config, relevant = _configured(cid, routing)
        state = _probe(cid).state
        if has_config:
            configured.append(cid)
        elif relevant and state == "on":
            on_but_empty.append(cid)
    data = {"configured": configured, "on_but_empty": on_but_empty}
    if on_but_empty:
        return CheckResult(
            id="connectors", status="fail",
            summary=f"connected but not configured: {', '.join(on_but_empty)}",
            detail="These show 'on' in the app because a credential exists, but no account (90-meta/accounts.yaml) or routing block (github orgs, joplin, claude_code) is configured, so every sync returns zero events. Reconnect through the app or add the account/org.",
            fix=Fix(kind="manual", command="open the connector card in the app and finish its form, then run `poltergeist <connector>-fetch`"),
            data=data,
        )
    if not configured:
        return CheckResult(
            id="connectors", status="warn", summary="no connectors configured yet",
            fix=Fix(kind="manual", command="connect one from the app's connectors screen"),
            data=data,
        )
    return CheckResult(id="connectors", status="ok", summary=", ".join(configured), data=data)


@register("claude-hook")
def check_claude_hook() -> CheckResult:
    try:
        doc = claude_settings.load()
    except ValueError as e:
        return CheckResult(
            id="claude-hook", status="fail", summary="~/.claude/settings.json is not valid JSON",
            detail=str(e), fix=Fix(kind="manual", command="fix the JSON by hand, then re-run doctor"),
        )
    cmds = claude_settings.session_end_commands(doc)
    if not cmds:
        return CheckResult(
            id="claude-hook", status="fail", summary="no SessionEnd hook in ~/.claude/settings.json",
            detail="The hook queues each finished Claude Code session into the vault.",
            fix=Fix(kind="automated", command="setup install-hook"),
        )
    stale = [c for c in cmds if not claude_settings.hook_command_exists(c)]
    if stale:
        return CheckResult(
            id="claude-hook", status="fail", summary="SessionEnd hook points at a missing script",
            detail="\n".join(stale),
            fix=Fix(kind="automated", command="setup install-hook"),
        )
    return CheckResult(id="claude-hook", status="ok", summary=cmds[0])


@register("cli-shim")
def check_cli_shim() -> CheckResult:
    path = shutil.which("poltergeist")
    if path:
        return CheckResult(id="cli-shim", status="ok", summary=path)
    return CheckResult(
        id="cli-shim", status="warn", summary="`poltergeist` not on PATH",
        detail="Optional. Lets you run connector commands as `poltergeist <sub>` instead of the full bundle path.",
        fix=Fix(kind="automated", command="setup cli-shim"),
    )
