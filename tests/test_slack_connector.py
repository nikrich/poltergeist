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
    monkeypatch.delenv("SLACK_TOKEN_ACME", raising=False)
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)

    path = auth_mod.save_token("acme", "xoxp-test-token-1234")
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
    assert auth_mod.load_token("acme") == "xoxp-test-token-1234"


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
        auth_mod.save_token("acme", "not-a-token")


def test_auth_slug_normalizes_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)
    path = auth_mod.token_path("Acme Rockets")
    assert path.name == "slack.acme_rockets.token"


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
    auth_mod.save_token("acme", "xoxp-from-file")
    monkeypatch.setenv("SLACK_TOKEN_ACME", "xoxp-from-env")
    assert auth_mod.load_token("acme") == "xoxp-from-env"


def test_auth_env_var_name_capitalises_and_dashes() -> None:
    from ghostbrain.connectors.slack import auth as auth_mod
    assert auth_mod.env_var_name("acme") == "SLACK_TOKEN_ACME"
    assert auth_mod.env_var_name("consulting-tech") == "SLACK_TOKEN_CONSULTING_TECH"
    assert auth_mod.env_var_name("Acme Rockets") == "SLACK_TOKEN_ACME_ROCKETS"


def test_auth_env_var_rejects_garbage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_TOKEN_ACME", "not-a-real-token")
    import importlib
    from ghostbrain.connectors.slack import auth as auth_mod
    importlib.reload(auth_mod)
    with pytest.raises(auth_mod.SlackAuthError, match="xoxp"):
        auth_mod.load_token("acme")


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
    title = _build_title(channel_name="dev-rockets", is_dm=False,
                          is_mpim=False, user_name="alex", text="@you ping")
    assert title.startswith("#dev-rockets:")


def test_build_title_truncates_long_text() -> None:
    from ghostbrain.connectors.slack.connector import _build_title
    title = _build_title(channel_name="x", is_dm=False, is_mpim=False,
                          user_name="alex", text="A" * 200)
    assert title.endswith("…")
    assert "AAAA" in title


def test_parse_workspaces_skips_entries_without_context(caplog) -> None:
    from ghostbrain.connectors.slack.connector import _parse_workspaces
    out = list(_parse_workspaces({"workspaces": {
        "acme": {"context": "work"},
        "broken": {"lookback_hours": 24},  # no context
    }}))
    slugs = [ws.slug for ws in out]
    assert "acme" in slugs
    assert "broken" not in slugs


def test_parse_workspaces_normalizes_allowed_channels() -> None:
    """allowed_channels accepts ``#foo`` or ``foo``, case-insensitive."""
    from ghostbrain.connectors.slack.connector import _parse_workspaces
    [ws] = list(_parse_workspaces({"workspaces": {
        "acme": {
            "context": "work",
            "mode": "full",
            "allowed_channels": ["#General", "Project-Alpha", "#general"],
        },
    }}))
    assert ws.allowed_channels == ("general", "project-alpha", "general")


def test_parse_workspaces_env_var_overrides_yaml_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SLACK_ALLOWED_CHANNELS_<SLUG> wins over routing.yaml so sensitive
    channel names can stay out of any committed/synced yaml."""
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS_ACME", "alpha, #beta , gamma")
    from ghostbrain.connectors.slack.connector import _parse_workspaces
    [ws] = list(_parse_workspaces({"workspaces": {
        "acme": {
            "context": "work",
            "mode": "full",
            "allowed_channels": ["ignored-because-env-wins"],
        },
    }}))
    assert ws.allowed_channels == ("alpha", "beta", "gamma")


def test_parse_workspaces_state_file_overrides_env_and_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The state file at ~/.ghostbrain/state/slack.<slug>.allowed_channels.json
    is the highest-priority source. It doesn't rely on env-var
    propagation through the packaged-app launcher (in v0.2.0 the
    sidecar inherited the slack token from .env but not the allowlist
    from the same file, with no error)."""
    import json
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS_ACME", "ignored-because-state-file-wins")
    (tmp_path / "slack.acme.allowed_channels.json").write_text(
        json.dumps(["#first", "second", "Third"]),
        encoding="utf-8",
    )

    from ghostbrain.connectors.slack.connector import _parse_workspaces
    [ws] = list(_parse_workspaces({"workspaces": {
        "acme": {
            "context": "work",
            "mode": "full",
            "allowed_channels": ["also-ignored"],
        },
    }}))
    assert ws.allowed_channels == ("first", "second", "third")


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
    channel_name: str = "dev-rockets",
    is_im: bool = False,
    is_mpim: bool = False,
    permalink: str = "https://acme.slack.com/archives/C123/p1715000000001",
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
        workspace_slug="acme",
        workspace_team_id="T1",
        workspace_name="Acme Rockets",
        my_user_id="U-me",
    )
    assert ev is not None
    assert ev["source"] == "slack"
    assert ev["type"] == "slack_message"
    assert ev["subtype"] == "mention"
    assert ev["id"] == "slack:msg:T1:C123:1715000000.001"
    assert ev["title"].startswith("#dev-rockets:")
    md = ev["metadata"]
    assert md["workspace_slug"] == "acme"
    assert md["workspace_id"] == "T1"
    assert md["channel_name"] == "dev-rockets"
    assert md["user_name"] == "alex"
    assert md["my_user_id"] == "U-me"


def test_normalize_match_dm() -> None:
    from ghostbrain.connectors.slack.connector import _normalize_match
    ev = _normalize_match(
        _match(channel_id="D456", channel_name="", is_im=True,
                username="alex"),
        workspace_slug="acme", workspace_team_id="T1",
        workspace_name="Work", my_user_id="U-me",
    )
    assert ev is not None
    assert ev["title"].startswith("DM with alex:")
    assert ev["metadata"]["is_dm"] is True


def test_normalize_match_skips_when_ts_missing() -> None:
    from ghostbrain.connectors.slack.connector import _normalize_match
    ev = _normalize_match(
        _match(ts=""),
        workspace_slug="acme", workspace_team_id="T1",
        workspace_name="Work", my_user_id="U-me",
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
    auth_mod.save_token("acme", "xoxp-test")
    # Re-import the connector module so it sees the reloaded auth.
    from ghostbrain.connectors.slack import connector as conn_mod
    importlib.reload(conn_mod)

    fake = MagicMock()
    fake.auth_test.return_value = {
        "user_id": "U-me", "team_id": "T1", "team": "Acme Rockets",
    }
    fake.search_messages.return_value = {
        "messages": {
            "matches": [_match(ts="1715000000.001"),
                         _match(ts="1715000010.000",
                                channel_name="ci-builds")],
        },
    }

    c = conn_mod.SlackConnector(
        config={"workspaces": {"acme": {"context": "work"}}},
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


def test_fetch_falls_back_to_mentions_when_full_mode_has_no_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Without an allowlist, full-pull on a large workspace silently fails
    (every channel hits rate limit, per-channel except-block swallows it,
    last_run_ok=true, queued=0). Refuse the footgun: fall back to mentions
    so the user still gets @-mentions/DMs while they configure channels."""
    from ghostbrain.connectors.slack import auth as auth_mod
    import importlib
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    importlib.reload(auth_mod)
    auth_mod.save_token("acme", "xoxp-test")

    from ghostbrain.connectors.slack import connector as conn_mod
    importlib.reload(conn_mod)

    fake = MagicMock()
    fake.auth_test.return_value = {
        "user_id": "U-me", "team_id": "T1", "team": "Acme",
    }
    fake.search_messages.return_value = {
        "messages": {"matches": [_match()]},
    }

    c = conn_mod.SlackConnector(
        config={"workspaces": {"acme": {"context": "work", "mode": "full"}}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        client_factory=lambda token: fake,
    )

    events = c.fetch(datetime.now(timezone.utc))
    # search.messages (mentions path) was called, not conversations.history.
    fake.search_messages.assert_called_once()
    assert len(events) == 1


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
            "good": {"context": "work"},
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
        "metadata": {"workspace_slug": "acme"},
    }
    routing = {"slack": {"workspaces": {"acme": {"context": "work"}}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "work"
    assert decision.method == "path"
    assert decision.confidence == 1.0


def test_router_supports_legacy_string_value() -> None:
    """Older routing.yaml format may have ``slack.workspaces: {acme: work}``
    — string value instead of dict. Accept it."""
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "slack",
        "id": "slack:msg:T1:C1:123.456",
        "metadata": {"workspace_slug": "acme"},
    }
    routing = {"slack": {"workspaces": {"acme": "work"}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "work"


def test_router_falls_through_when_workspace_unknown() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "slack",
        "id": "slack:msg:T1:C1:123.456",
        "metadata": {"workspace_slug": "stranger"},
    }
    routing = {"slack": {"workspaces": {"acme": {"context": "work"}}}}
    assert _fast_route(event, routing) is None


# ---------------------------------------------------------------------------
# Full-pull DM / group-DM inclusion
# ---------------------------------------------------------------------------


def _full_pull_connector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ws_cfg: dict,
):
    """Full-mode connector against a fake client whose workspace has one
    public channel (in the allowlist), one DM, and one group DM."""
    from ghostbrain.connectors.slack import auth as auth_mod
    import importlib
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    importlib.reload(auth_mod)
    auth_mod.save_token("acme", "xoxp-test")
    from ghostbrain.connectors.slack import connector as conn_mod
    importlib.reload(conn_mod)

    fake = MagicMock()
    fake.auth_test.return_value = {
        "user_id": "U-me", "team_id": "T1", "team": "Acme",
    }
    fake.users_conversations.return_value = {
        "channels": [
            {"id": "C1", "name": "engineering"},
            {"id": "D1", "is_im": True, "user": "U-alice"},
            {"id": "G1", "name": "mpdm-alice--bob--me-1", "is_mpim": True},
        ],
        "response_metadata": {"next_cursor": ""},
    }

    def history(**kwargs):
        msgs = {
            "C1": [{"ts": "1785000000.000100", "user": "U-alice",
                    "text": "channel message"}],
            "D1": [{"ts": "1785000001.000100", "user": "U-alice",
                    "text": "dm for your eyes"}],
            "G1": [{"ts": "1785000002.000100", "user": "U-bob",
                    "text": "<@U-me> group dm ping"}],
        }
        return {"messages": msgs[kwargs["channel"]], "has_more": False}

    fake.conversations_history.side_effect = history

    c = conn_mod.SlackConnector(
        config={"workspaces": {"acme": {
            "context": "work", "mode": "full", "llm_filter": False,
            **ws_cfg,
        }}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        client_factory=lambda token: fake,
    )
    return c


def test_full_pull_allowlist_drops_dms_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    c = _full_pull_connector(
        monkeypatch, tmp_path, {"allowed_channels": ["engineering"]},
    )
    events = c.fetch(datetime.now(timezone.utc))
    texts = [e["body"] for e in events]
    assert any("channel message" in t for t in texts)
    assert not any("dm for your eyes" in t for t in texts)
    assert not any("group dm ping" in t for t in texts)


def test_full_pull_include_dms_pulls_ims_past_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    c = _full_pull_connector(
        monkeypatch, tmp_path,
        {"allowed_channels": ["engineering"], "include_dms": True},
    )
    events = c.fetch(datetime.now(timezone.utc))
    texts = [e["body"] for e in events]
    assert any("dm for your eyes" in t for t in texts)
    # group DMs stay excluded unless their own flag is set
    assert not any("group dm ping" in t for t in texts)


def test_full_pull_include_group_dms_pulls_mpims_past_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    c = _full_pull_connector(
        monkeypatch, tmp_path,
        {"allowed_channels": ["engineering"], "include_group_dms": True},
    )
    events = c.fetch(datetime.now(timezone.utc))
    texts = [e["body"] for e in events]
    assert any("group dm ping" in t for t in texts)
    assert not any("dm for your eyes" in t for t in texts)


def test_full_pull_dms_only_does_not_fall_back_to_mentions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """include_dms with no allowlist is a valid bounded config (only im
    conversations get history calls) — it must not trip the
    no-allowlist mentions fallback."""
    c = _full_pull_connector(monkeypatch, tmp_path, {"include_dms": True})
    events = c.fetch(datetime.now(timezone.utc))
    texts = [e["body"] for e in events]
    assert any("dm for your eyes" in t for t in texts)
    assert not any("channel message" in t for t in texts)
    fake = c._client_factory("x")
    fake.search_messages.assert_not_called()


def test_parse_workspaces_reads_dm_flags() -> None:
    from ghostbrain.connectors.slack.connector import _parse_workspaces
    (ws,) = _parse_workspaces({"workspaces": {"acme": {
        "context": "work", "mode": "full",
        "include_dms": True, "include_group_dms": True,
    }}})
    assert ws.include_dms is True
    assert ws.include_group_dms is True
