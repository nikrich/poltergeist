"""Cheap, offline credential-presence probes per connector.

Classifies a connector as off (no credential), on (credential present),
or err (credential present but structurally unusable). NO network calls —
liveness/validation that needs the network happens on explicit user action
(the auth router's validate step), not on every list call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ghostbrain.paths import state_dir, vault_path


@dataclass
class ProbeResult:
    state: str
    account: str | None = None
    error: str | None = None


def _slug_to_email(token_filename: str, prefix: str) -> str | None:
    # "gmail.you_at_gmail_com.token" -> "you@gmail.com"
    stem = token_filename[len(prefix) + 1 : -len(".token")]
    if "_at_" not in stem:
        return None
    local, _, domain = stem.partition("_at_")
    return f"{local}@{domain.replace('_', '.')}"


def _google_probe(prefix: str) -> ProbeResult:
    d = state_dir()
    tokens = sorted(d.glob(f"{prefix}.*.token"))
    if not tokens:
        return ProbeResult("off")
    account = _slug_to_email(tokens[0].name, prefix)
    return ProbeResult("on", account=account)


def _slack_probe() -> ProbeResult:
    files = sorted(state_dir().glob("slack.*.token"))
    if files:
        return ProbeResult("on", account=files[0].name[len("slack.") : -len(".token")])
    # env fallback (SLACK_TOKEN_*)
    if any(k.startswith("SLACK_TOKEN_") and os.environ[k].strip() for k in os.environ):
        return ProbeResult("on")
    return ProbeResult("off")


def _joplin_probe() -> ProbeResult:
    from ghostbrain.api.repo.routing import load_routing  # Task B1

    token = (load_routing().get("joplin") or {}).get("token")
    return ProbeResult("on") if token else ProbeResult("off")


def _atlassian_probe(connector_id: str) -> ProbeResult:
    from ghostbrain.api.repo.routing import load_routing

    sites = ((load_routing().get(connector_id) or {}).get("sites")) or {}
    if not sites:
        return ProbeResult("off")

    email = os.environ.get("ATLASSIAN_EMAIL")
    has_token = any(
        k == "ATLASSIAN_TOKEN" or k.startswith("ATLASSIAN_TOKEN_")
        for k in os.environ
    )
    if email and has_token:
        return ProbeResult("on", account=email)
    if email or has_token:
        return ProbeResult("err", account=email, error="Atlassian email or token missing")
    return ProbeResult("off")


def _microsoft_probe() -> ProbeResult:
    from ghostbrain.connectors.microsoft.graph.auth import cache_location

    return ProbeResult("on") if cache_location().exists() else ProbeResult("off")


def _github_probe() -> ProbeResult:
    import shutil
    import subprocess

    if shutil.which("gh") is None:
        return ProbeResult("off")
    try:
        r = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, timeout=5, text=True
        )
    except (subprocess.SubprocessError, OSError):
        return ProbeResult("off")
    return ProbeResult("on") if r.returncode == 0 else ProbeResult("off")


def _claude_code_probe() -> ProbeResult:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return ProbeResult("off")
    try:
        import json

        hooks = json.loads(settings.read_text()).get("hooks", {})
    except (OSError, ValueError):
        return ProbeResult("off")
    return ProbeResult("on") if "SessionEnd" in hooks else ProbeResult("off")


def probe(connector_id: str) -> ProbeResult:
    if connector_id == "gmail":
        return _google_probe("gmail")
    if connector_id == "calendar":
        # Google token OR macOS is always locally available; treat google token
        # as the "on" signal, else off (macOS grant tracked separately in UI).
        return _google_probe("google_calendar")
    if connector_id == "slack":
        return _slack_probe()
    if connector_id == "joplin":
        return _joplin_probe()
    if connector_id in ("jira", "confluence"):
        return _atlassian_probe(connector_id)
    if connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        return _microsoft_probe()
    if connector_id == "github":
        return _github_probe()
    if connector_id == "claude_code":
        return _claude_code_probe()
    return ProbeResult("off")
