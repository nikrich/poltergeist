"""Tests for the new Slack helpers added in the full-pull refactor:
``_extract_text``, ``_is_noise``, and ``_always_keep_reason``.

These ride on real Slack message shapes — the docstrings note the
source so it's clear we're not just shadow-boxing test fixtures.
"""

from __future__ import annotations

from ghostbrain.connectors.slack.connector import (
    _always_keep_reason,
    _extract_text,
    _is_noise,
)


# ---------------------------------------------------------------------------
# _extract_text — pull readable content from any of Slack's three slots
# ---------------------------------------------------------------------------


def test_extract_text_uses_top_level_when_present() -> None:
    assert _extract_text({"text": "hello"}) == "hello"


def test_extract_text_falls_back_to_attachments() -> None:
    """DLQ-alert-style bot messages: top-level text empty, attachments[0].text
    carries the payload."""
    m = {
        "text": "",
        "bot_id": "B1",
        "attachments": [
            {"text": ":rotating_light: DLQ Alert: queue=foo", "fallback": ""},
        ],
    }
    assert "DLQ Alert" in _extract_text(m)


def test_extract_text_walks_attachment_fields_in_priority_order() -> None:
    """Per-attachment priority: pretext → title → text → fallback."""
    m = {"text": "", "attachments": [{"title": "Build #42", "text": "passed"}]}
    extracted = _extract_text(m)
    # title is the first non-empty in the priority list
    assert "Build #42" in extracted


def test_extract_text_reads_blocks_when_others_empty() -> None:
    """Modern Slack messages may live entirely in blocks[]."""
    m = {"text": "", "blocks": [{"type": "section", "text": {"text": "Deploy succeeded"}}]}
    assert _extract_text(m) == "Deploy succeeded"


def test_extract_text_combines_top_level_and_attachment() -> None:
    """When both have content, both end up in the output (LLM gets full
    context for triage)."""
    m = {
        "text": "FYI from CI",
        "attachments": [{"text": "200 tests passed"}],
    }
    out = _extract_text(m)
    assert "FYI from CI" in out
    assert "200 tests passed" in out


def test_extract_text_empty_when_truly_empty() -> None:
    assert _extract_text({}) == ""
    assert _extract_text({"text": "", "attachments": [], "blocks": []}) == ""


# ---------------------------------------------------------------------------
# _is_noise — system events + content-less messages
# ---------------------------------------------------------------------------


def test_is_noise_system_subtypes() -> None:
    """The launchd/legacy connector used to surface channel_join etc as
    "events" — the full-pull path drops them."""
    for sub in ("channel_join", "channel_leave", "pinned_item", "reminder_add"):
        assert _is_noise({"subtype": sub})


def test_is_noise_drops_messages_with_no_extractable_content() -> None:
    """File uploads with no caption, pure-blocks layouts we can't parse —
    nothing the LLM can judge, so we skip rather than waste the round-trip."""
    assert _is_noise({"text": ""})
    assert _is_noise({"text": "", "attachments": []})


def test_is_noise_keeps_real_messages() -> None:
    assert not _is_noise({"text": "hey team"})
    assert not _is_noise({"text": "", "attachments": [{"text": "deploy ok"}]})


# ---------------------------------------------------------------------------
# _always_keep_reason — bypass the LLM gate for high-signal paths
# ---------------------------------------------------------------------------


def test_mention_bypasses_gate() -> None:
    assert _always_keep_reason(
        {"text": "hey <@U999>"}, {}, my_user_id="U999",
    ) == "mention"


def test_dm_bypasses_gate() -> None:
    assert _always_keep_reason(
        {"text": "hi"}, {"is_im": True}, my_user_id="U999",
    ) == "dm"


def test_my_own_message_bypasses_gate() -> None:
    """The user's own messages capture commitments, decisions, and the
    state of their own thinking — always worth indexing."""
    assert _always_keep_reason(
        {"text": "I'll ship this tomorrow", "user": "U999"}, {}, my_user_id="U999",
    ) == "my_message"


def test_ambient_message_goes_through_gate() -> None:
    """Public-channel chatter from someone else with no mention — this is
    what the LLM filter exists to triage."""
    assert _always_keep_reason(
        {"text": "deploy looks fine", "user": "U001"}, {}, my_user_id="U999",
    ) is None
