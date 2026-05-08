"""Tests for the Slack connector. The slack-sdk WebClient is replaced
with a MagicMock dict-returning double — no network, no token reads."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_auth_save_and_load_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SLACK_TOKEN_SFT", raising=False)
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)

    path = auth_mod.save_token("sft", "xoxp-test-token-1234")
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
    assert auth_mod.load_token("sft") == "xoxp-test-token-1234"


def test_auth_load_missing_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SLACK_TOKEN_MISSING", raising=False)
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)

    with pytest.raises(auth_mod.SlackAuthError, match="No Slack token"):
        auth_mod.load_token("missing")


def test_auth_save_rejects_garbage_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)

    with pytest.raises(auth_mod.SlackAuthError, match="xoxp-"):
        auth_mod.save_token("sft", "not-a-token")


def test_auth_slug_normalizes_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)
    path = auth_mod.token_path("Sanlam Capstone")
    assert path.name == "slack.sanlam_capstone.token"


def test_auth_env_var_takes_precedence_over_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Env-var path is the first-class lookup so .env-driven setups
    work without an extra CLI step. The file is just the fallback."""
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)

    # Both sources present — env wins.
    auth_mod.save_token("sft", "xoxp-from-file")
    monkeypatch.setenv("SLACK_TOKEN_SFT", "xoxp-from-env")
    assert auth_mod.load_token("sft") == "xoxp-from-env"


def test_auth_env_var_name_capitalises_and_dashes() -> None:
    from ghostbrain.connectors.slack import auth as auth_mod
    assert auth_mod.env_var_name("sft") == "SLACK_TOKEN_SFT"
    assert auth_mod.env_var_name("codeship-tech") == "SLACK_TOKEN_CODESHIP_TECH"
    assert auth_mod.env_var_name("Sanlam Capstone") == "SLACK_TOKEN_SANLAM_CAPSTONE"


def test_auth_env_var_rejects_garbage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_TOKEN_SFT", "not-a-real-token")
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)
    with pytest.raises(auth_mod.SlackAuthError, match="xoxp"):
        auth_mod.load_token("sft")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_slack_ts_to_iso() -> None:
    from ghostbrain.connectors.slack.connector import _slack_ts_to_iso
    iso = _slack_ts_to_iso("1715000000.001234")
    assert iso.startswith("2024-")  # 1715000000 ≈ May 2024


def test_build_title_for_dm() -> None:
    from ghostbrain.connectors.slack.connector import _build_title
    title = _build_title(channel_name="", is_dm=True, is_mpim=False,
                          user_name="alex", text="hey, can you check this?")
    assert title.startswith("DM with alex:")


def test_build_title_for_channel() -> None:
    from ghostbrain.connectors.slack.connector import _build_title
    title = _build_title(channel_name="dev-capstone", is_dm=False,
                          is_mpim=False, user_name="alex", text="@you ping")
    assert title.startswith("#dev-capstone:")


def test_build_title_truncates_long_text() -> None:
    from ghostbrain.connectors.slack.connector import _build_title
    title = _build_title(channel_name="x", is_dm=False, is_mpim=False,
                          user_name="alex", text="A" * 200)
    assert title.endswith("…")
    assert "AAAA" in title


def test_parse_workspaces_skips_entries_without_context(caplog) -> None:
    from ghostbrain.connectors.slack.connector import _parse_workspaces
    out = list(_parse_workspaces({"workspaces": {
        "sft": {"context": "sanlam"},
        "broken": {"lookback_hours": 24},  # no context
    }}))
    slugs = [ws.slug for ws in out]
    assert "sft" in slugs
    assert "broken" not in slugs


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------


def _match(
    *,
    text: str = "Hey @you, ship this PR?",
    user: str = "U999",
    username: str = "alex",
    ts: str = "1715000000.001",
    channel_id: str = "C123",
    channel_name: str = "dev-capstone",
    is_im: bool = False,
    is_mpim: bool = False,
    permalink: str = "https://sft.slack.com/archives/C123/p1715000000001",
) -> dict:
    return {
        "text": text,
        "user": user,
        "username": username,
        "ts": ts,
        "channel": {
            "id": channel_id,
            "name": channel_name,
            "is_im": is_im,
            "is_mpim": is_mpim,
        },
        "permalink": permalink,
    }


def test_normalize_match_channel_mention() -> None:
    from ghostbrain.connectors.slack.connector import _normalize_match
    ev = _normalize_match(
        _match(),
        workspace_slug="sft",
        workspace_team_id="T1",
        workspace_name="Sanlam Capstone",
        my_user_id="U-me",
    )
    assert ev is not None
    assert ev["source"] == "slack"
    assert ev["type"] == "slack_message"
    assert ev["subtype"] == "mention"
    assert ev["id"] == "slack:msg:T1:C123:1715000000.001"
    assert ev["title"].startswith("#dev-capstone:")
    md = ev["metadata"]
    assert md["workspace_slug"] == "sft"
    assert md["workspace_id"] == "T1"
    assert md["channel_name"] == "dev-capstone"
    assert md["user_name"] == "alex"
    assert md["my_user_id"] == "U-me"


def test_normalize_match_dm() -> None:
    from ghostbrain.connectors.slack.connector import _normalize_match
    ev = _normalize_match(
        _match(channel_id="D456", channel_name="", is_im=True,
                username="alex"),
        workspace_slug="sft", workspace_team_id="T1",
        workspace_name="Sanlam", my_user_id="U-me",
    )
    assert ev is not None
    assert ev["title"].startswith("DM with alex:")
    assert ev["metadata"]["is_dm"] is True


def test_normalize_match_skips_when_ts_missing() -> None:
    from ghostbrain.connectors.slack.connector import _normalize_match
    ev = _normalize_match(
        _match(ts=""),
        workspace_slug="sft", workspace_team_id="T1",
        workspace_name="Sanlam", my_user_id="U-me",
    )
    assert ev is None


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def test_fetch_skips_when_no_workspaces(tmp_path: Path) -> None:
    from ghostbrain.connectors.slack import SlackConnector
    c = SlackConnector(
        config={"workspaces": {}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    assert c.fetch(datetime.now(timezone.utc)) == []


def test_fetch_one_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from ghostbrain.connectors.slack import SlackConnector
    from ghostbrain.connectors.slack import auth as auth_mod
    import importlib
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    importlib.reload(auth_mod)
    auth_mod.save_token("sft", "xoxp-test")
    # Re-import the connector module so it sees the reloaded auth.
    from ghostbrain.connectors.slack import connector as conn_mod
    importlib.reload(conn_mod)

    fake = MagicMock()
    fake.auth_test.return_value = {
        "user_id": "U-me", "team_id": "T1", "team": "Sanlam Capstone",
    }
    fake.search_messages.return_value = {
        "messages": {
            "matches": [_match(ts="1715000000.001"),
                         _match(ts="1715000010.000",
                                channel_name="ci-builds")],
        },
    }

    c = conn_mod.SlackConnector(
        config={"workspaces": {"sft": {"context": "sanlam"}}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        client_factory=lambda token: fake,
    )

    events = c.fetch(datetime.now(timezone.utc))
    assert len(events) == 2
    fake.auth_test.assert_called_once()
    fake.search_messages.assert_called_once()
    # The query should target our user_id and have a date floor.
    kwargs = fake.search_messages.call_args.kwargs
    assert "<@U-me>" in kwargs["query"]
    assert "after:" in kwargs["query"]


def test_fetch_continues_after_workspace_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """One bad workspace shouldn't break the others."""
    from ghostbrain.connectors.slack import auth as auth_mod
    import importlib
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    importlib.reload(auth_mod)
    auth_mod.save_token("good", "xoxp-good")
    # `bad` workspace has no token saved → SlackAuthError.

    from ghostbrain.connectors.slack import connector as conn_mod
    importlib.reload(conn_mod)

    fake = MagicMock()
    fake.auth_test.return_value = {
        "user_id": "U-me", "team_id": "T1", "team": "good team",
    }
    fake.search_messages.return_value = {"messages": {"matches": [_match()]}}

    c = conn_mod.SlackConnector(
        config={"workspaces": {
            "bad": {"context": "personal"},
            "good": {"context": "sanlam"},
        }},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        client_factory=lambda token: fake,
    )
    events = c.fetch(datetime.now(timezone.utc))
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Routing fast path
# ---------------------------------------------------------------------------


def test_router_routes_by_workspace_slug() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "slack",
        "id": "slack:msg:T1:C1:123.456",
        "metadata": {"workspace_slug": "sft"},
    }
    routing = {"slack": {"workspaces": {"sft": {"context": "sanlam"}}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "sanlam"
    assert decision.method == "path"
    assert decision.confidence == 1.0


def test_router_supports_legacy_string_value() -> None:
    """Older routing.yaml format may have ``slack.workspaces: {sft: sanlam}``
    — string value instead of dict. Accept it."""
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "slack",
        "id": "slack:msg:T1:C1:123.456",
        "metadata": {"workspace_slug": "sft"},
    }
    routing = {"slack": {"workspaces": {"sft": "sanlam"}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "sanlam"


def test_router_falls_through_when_workspace_unknown() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "slack",
        "id": "slack:msg:T1:C1:123.456",
        "metadata": {"workspace_slug": "stranger"},
    }
    routing = {"slack": {"workspaces": {"sft": {"context": "sanlam"}}}}
    assert _fast_route(event, routing) is None
