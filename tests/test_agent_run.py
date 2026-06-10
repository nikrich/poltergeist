"""run_chat_turn: subprocess lifecycle, timeout, resume-failure detection."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

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
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None, timeout_s=1))
    assert [e["type"] for e in events[:2]] == ["session", "delta"]
    assert events[-1]["type"] == "error"
    assert events[-1].get("interrupted") is True
