"""Slack token loading.

Slack's User OAuth flow is interactive and per-workspace. To keep setup
simple we use file-based tokens: the user creates a Slack app, installs
it to their workspace once, copies the User OAuth Token (``xoxp-...``)
into ``~/.ghostbrain/state/slack.<workspace_slug>.token``, and we read
it from there. No OAuth dance, no refresh logic — Slack User Tokens
don't expire unless the user revokes them.

Required User Token scopes for the connector:
- ``search:read`` (find mentions)
- ``users:read`` (resolve user IDs to names)
- ``team:read`` (workspace name)
- ``channels:history``, ``groups:history``, ``im:history``,
  ``mpim:history`` (read messages we matched)

The CLI helper ``ghostbrain-slack-token-add`` writes the file with the
right name + permissions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.slack.auth")


class SlackAuthError(RuntimeError):
    """Raised when a workspace token is missing or unreadable."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def token_path(workspace_slug: str) -> Path:
    safe = workspace_slug.lower().replace("/", "_").replace(" ", "_")
    return state_dir() / f"slack.{safe}.token"


def env_var_name(workspace_slug: str) -> str:
    """Canonical env var for a workspace token (e.g. ``SLACK_TOKEN_SFT``)."""
    safe = workspace_slug.upper().replace("-", "_").replace("/", "_")
    safe = safe.replace(" ", "_")
    return f"SLACK_TOKEN_{safe}"


def load_token(workspace_slug: str) -> str:
    """Look up the User OAuth Token for a workspace.

    Lookup order:
    1. Env var ``SLACK_TOKEN_<UPPER_SLUG>`` (auto-loaded from .env)
    2. File at ``~/.ghostbrain/state/slack.<slug>.token``

    The env-var path makes ``.env``-driven setups (single secrets file
    for the whole project) work without an extra CLI step. The
    file path supports per-workspace 0600 storage.
    """
    env_token = (os.environ.get(env_var_name(workspace_slug)) or "").strip()
    if env_token:
        if not env_token.startswith(("xoxp-", "xoxb-")):
            raise SlackAuthError(
                f"Env var {env_var_name(workspace_slug)} is set but doesn't "
                f"look like xoxp-/xoxb-."
            )
        return env_token

    path = token_path(workspace_slug)
    if not path.exists():
        raise SlackAuthError(
            f"No Slack token for workspace {workspace_slug!r}. "
            f"Set env var {env_var_name(workspace_slug)} in .env, or save "
            f"the token to {path} via "
            f"ghostbrain-slack-token-add {workspace_slug} <token>."
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SlackAuthError(f"Slack token at {path} is empty")
    if not token.startswith(("xoxp-", "xoxb-")):
        raise SlackAuthError(
            f"Slack token at {path} doesn't look like xoxp-/xoxb- — "
            "did you paste the right value?"
        )
    return token


def save_token(workspace_slug: str, token: str) -> Path:
    """Write a token to the canonical path with 0600 permissions."""
    token = token.strip()
    if not token.startswith(("xoxp-", "xoxb-")):
        raise SlackAuthError(
            "Token must start with xoxp- (User OAuth) or xoxb- (Bot)."
        )
    path = token_path(workspace_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    log.info("saved slack token for %s → %s", workspace_slug, path)
    return path
