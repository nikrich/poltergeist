"""run_chat_turn: subprocess lifecycle, timeout, resume-failure detection."""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from ghostbrain.llm import agent as agent_mod
from ghostbrain.llm.agent import ResumeFailed, run_chat_turn


def fake_claude(tmp_path: Path, body: str) -> str:
    """Write an executable shell script that ignores its args."""
    p = tmp_path / "fake-claude"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


HAPPY = r"""
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sess-1"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}
{"type":"result","subtype":"success","result":"hi","session_id":"sess-1"}
EOF
"""


def test_happy_path_yields_events_in_order(tmp_path: Path):
    binary = fake_claude(tmp_path, HAPPY)
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None))
    assert [e["type"] for e in events] == ["session", "delta", "done"]
    assert events[-1]["text"] == "hi"


def test_missing_binary_yields_error(monkeypatch: pytest.MonkeyPatch):
    # _find_claude_binary also probes well-known install paths (~/.local/bin
    # etc.), so env vars alone can't hide a locally installed claude — stub
    # the lookup itself.
    monkeypatch.setattr("ghostbrain.llm.agent._find_claude_binary", lambda: None)
    events = list(run_chat_turn("q", binary=None, mcp_binary=None))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "claude" in events[0]["message"]


def test_resume_failure_raises(tmp_path: Path):
    binary = fake_claude(tmp_path, 'echo "No conversation found" >&2\nexit 1\n')
    gen = run_chat_turn("q", session_id="stale", binary=binary, mcp_binary=None)
    with pytest.raises(ResumeFailed):
        list(gen)


def test_nonzero_exit_without_resume_yields_error(tmp_path: Path):
    binary = fake_claude(tmp_path, 'echo "boom" >&2\nexit 1\n')
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None))
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"]


def test_timeout_kills_process_and_yields_interrupted_error(tmp_path: Path):
    # Streams init + one delta but no result line, then hangs — the watchdog
    # must kill it and surface an interrupted error.
    body = r"""
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sess-1"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"par"}}}
EOF
sleep 30
"""
    binary = fake_claude(tmp_path, body)
    start = time.monotonic()
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None, timeout_s=1))
    elapsed = time.monotonic() - start
    # Group-kill regression guard: if only the direct child were killed, the
    # sleep-30 orphan would hold the stdout pipe open and this would take 30s.
    assert elapsed < 5
    assert [e["type"] for e in events[:2]] == ["session", "delta"]
    assert events[-1]["type"] == "error"
    assert events[-1].get("interrupted") is True


def test_cancel_turn_kills_subprocess_and_yields_stopped(tmp_path: Path):
    """cancel_turn() kills the claude subprocess and the generator yields a
    stopped error event.  Wall clock must be well under 30s."""
    body = r"""
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sess-1"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}
EOF
sleep 30
"""
    binary = fake_claude(tmp_path, body)
    start = time.monotonic()
    gen = run_chat_turn("q", binary=binary, mcp_binary=None, turn_key="conv-1")

    # Pull the two events that arrive before the sleep — generator is now
    # SUSPENDED at a yield (not blocked in readline), so cancel_turn can reach it.
    e1 = next(gen)
    e2 = next(gen)
    assert e1["type"] == "session"
    assert e2["type"] == "delta"

    # Kill the subprocess while the generator is suspended.
    assert agent_mod.cancel_turn("conv-1") is True

    # Exhaust the generator — readline unblocks immediately on EOF.
    remaining = list(gen)
    elapsed = time.monotonic() - start

    assert elapsed < 5
    assert remaining[-1] == {"type": "error", "message": "stopped", "interrupted": True}
    # Unregistered after generator exits.
    assert agent_mod.cancel_turn("conv-1") is False


def test_cancel_turn_on_resumed_turn_with_no_output_yields_stopped_not_resume_failed(
    tmp_path: Path,
):
    """A cancelled resumed turn that produced no parsed events must NOT raise
    ResumeFailed — cancelled takes priority in the post-loop classification.

    Mechanics: fake claude prints one non-JSON line then sleeps 30s (no events
    parse, so saw_any stays False).  We start the generator in a background
    thread, wait briefly for the subprocess to register, cancel it, then join
    and assert the stopped error was yielded instead of ResumeFailed.
    """
    import threading as _threading

    body = 'echo warming-up\nsleep 30\n'
    binary = fake_claude(tmp_path, body)

    gen = run_chat_turn(
        "q", session_id="s1", binary=binary, mcp_binary=None, turn_key="conv-2"
    )

    events: list[dict] = []
    exc_holder: list[BaseException] = []

    def drain():
        try:
            events.extend(gen)
        except BaseException as exc:  # noqa: BLE001
            exc_holder.append(exc)

    t = _threading.Thread(target=drain)
    t.start()

    # Give the subprocess time to start and register itself.
    time.sleep(0.3)
    agent_mod.cancel_turn("conv-2")

    t.join(timeout=5)
    assert not t.is_alive(), "generator did not finish after cancel"

    # Must not have raised ResumeFailed.
    assert not exc_holder, f"unexpected exception: {exc_holder[0]}"
    assert events[-1] == {"type": "error", "message": "stopped", "interrupted": True}


def test_write_doc_tool_is_allowlisted():
    from ghostbrain.llm.agent import ALLOWED_TOOLS

    assert "mcp__poltergeist__poltergeist_write_doc" in ALLOWED_TOOLS


def test_web_tools_are_allowlisted():
    from ghostbrain.llm.agent import ALLOWED_TOOLS

    assert "WebFetch" in ALLOWED_TOOLS
    assert "WebSearch" in ALLOWED_TOOLS
