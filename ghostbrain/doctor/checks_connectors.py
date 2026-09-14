"""Connector, Claude Code hook, and CLI shim checks (Task 5)."""
from __future__ import annotations

import shutil

from ghostbrain.api import claude_settings
from ghostbrain.doctor import CheckResult, Fix, register

# connector id -> (routing.yaml top-level key, sub-key that must be non-empty)
_BLOCKS: dict[str, tuple[str, str]] = {
    "github": ("github", "orgs"),
    "gmail": ("gmail", "accounts"),
    "calendar": ("calendar", "google"),
    "slack": ("slack", "workspaces"),
    "jira": ("jira", "sites"),
    "confluence": ("confluence", "sites"),
    "joplin": ("joplin", "token"),
    "claude_code": ("claude_code", "project_paths"),
}


def _routing() -> dict:
    from ghostbrain.api.repo.routing import load_routing

    return load_routing()


def _probe(connector_id: str):
    from ghostbrain.api.repo.connector_probe import probe

    return probe(connector_id)


def _block_non_empty(routing: dict, key: str, sub: str) -> bool:
    block = routing.get(key) or {}
    value = block.get(sub)
    if key == "calendar":
        macos = ((block.get("macos") or {}).get("accounts")) or {}
        google = ((block.get("google") or {}).get("accounts")) or {}
        return bool(macos or google)
    return bool(value)


@register("connectors")
def check_connectors() -> CheckResult:
    routing = _routing()
    configured: list[str] = []
    on_but_empty: list[str] = []
    for cid, (key, sub) in _BLOCKS.items():
        has_block = _block_non_empty(routing, key, sub)
        state = _probe(cid).state
        if has_block:
            configured.append(cid)
        elif key in routing and state == "on":
            on_but_empty.append(cid)
    data = {"configured": configured, "on_but_empty": on_but_empty}
    if on_but_empty:
        return CheckResult(
            id="connectors", status="fail",
            summary=f"connected but not configured: {', '.join(on_but_empty)}",
            detail="These show 'on' in the app because a credential exists, but their routing block is empty, so every sync returns zero events. Add the org/account/calendar to 90-meta/routing.yaml or reconnect through the app.",
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
