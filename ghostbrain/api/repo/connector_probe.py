"""Cheap, offline credential-presence probes per connector.

Classifies a connector as off (no credential), on (credential present),
or err (credential present but structurally unusable). NO network calls —
liveness/validation that needs the network happens on explicit user action
(the auth router's validate step), not on every list call.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from ghostbrain.paths import state_dir


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
    from ghostbrain import accounts
    from ghostbrain.connectors.atlassian._base import AtlassianAuthError, auth_for_site

    accts = accounts.list_accounts(connector_id)
    if not accts:
        return ProbeResult("off")
    try:
        email, _ = auth_for_site(accts[0].id)
    except AtlassianAuthError as e:
        return ProbeResult("err", error=str(e))
    return ProbeResult("on", account=email)


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
            ["gh", "auth", "status"], capture_output=True, timeout=5, text=True, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return ProbeResult("off")
    return ProbeResult("on") if r.returncode == 0 else ProbeResult("off")


def _claude_code_probe() -> ProbeResult:
    from ghostbrain.api import claude_settings

    try:
        doc = claude_settings.load()
    except ValueError:
        return ProbeResult("err", error="settings.json is not valid JSON")
    cmds = claude_settings.session_end_commands(doc)
    if not cmds:
        return ProbeResult("off")
    if not any(claude_settings.hook_command_exists(c) for c in cmds):
        return ProbeResult("err", error="SessionEnd hook points at a missing script; run `poltergeist setup install-hook`")
    return ProbeResult("on")


def _platform() -> str:
    return sys.platform


def _macos_calendar_authorized() -> bool | None:
    from ghostbrain.api.auth.providers.local_grant import _macos_calendar_authorized as impl

    return impl()


def _load_routing() -> dict:
    from ghostbrain.api.repo.routing import load_routing

    return load_routing()


def _whatsapp_store_status() -> tuple[str, str | None]:
    import sqlite3
    from contextlib import closing

    from ghostbrain.connectors.whatsapp import store

    try:
        with closing(store.open_store(store.default_store_path())) as conn:
            store.check_schema(conn)
    except FileNotFoundError:
        return "missing", None
    except store.StoreSchemaError as e:
        return "schema", str(e)
    except (PermissionError, sqlite3.OperationalError) as e:
        return "denied", str(e)
    except sqlite3.DatabaseError as e:
        return "schema", f"WhatsApp store is unreadable: {e}"
    return "ok", None


def _whatsapp_probe() -> ProbeResult:
    if _platform() != "darwin":
        return ProbeResult("off")
    from ghostbrain.connectors.whatsapp import allowlist

    # Opt-in first: no chats picked means off, without touching the store.
    n = len(allowlist.load(state_dir()))
    if n == 0:
        return ProbeResult("off")
    status, detail = _whatsapp_store_status()
    if status == "missing":
        return ProbeResult("off")
    if status == "denied":
        return ProbeResult("err", error="Grant Poltergeist Full Disk Access to read WhatsApp")
    if status == "schema":
        return ProbeResult("err", error=detail)
    return ProbeResult("on", account=f"{n} chat" + ("" if n == 1 else "s"))


def probe(connector_id: str) -> ProbeResult:
    if connector_id == "gmail":
        return _google_probe("gmail")
    if connector_id == "gdrive":
        return _google_probe("gdrive")
    if connector_id == "calendar":
        google = _google_probe("google_calendar")
        if google.state == "on" or _platform() != "darwin":
            return google
        accounts = (((_load_routing().get("calendar") or {}).get("macos") or {}).get("accounts")) or {}
        if accounts and _macos_calendar_authorized():
            return ProbeResult("on")
        return google
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
    if connector_id == "whatsapp":
        return _whatsapp_probe()
    return ProbeResult("off")
