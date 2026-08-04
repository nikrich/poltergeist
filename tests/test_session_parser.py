"""Tests for the Claude Code session JSONL parser."""

from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.connectors.claude_code.parser import (
    SessionDigest,
    derive_cwd_from_dirname,
    parse_transcript,
)


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_parse_extracts_user_and_assistant_text(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "permission-mode", "permissionMode": "auto",
         "sessionId": "abc"},
        {"type": "user", "sessionId": "abc",
         "timestamp": "2026-05-07T10:00:00Z",
         "message": {"content": "First user prompt"}},
        {"type": "assistant", "sessionId": "abc",
         "timestamp": "2026-05-07T10:00:01Z",
         "message": {"content": [{"type": "text", "text": "Sure, doing it."}]}},
        {"type": "user", "sessionId": "abc",
         "timestamp": "2026-05-07T10:01:00Z",
         "message": {"content": [
             {"type": "tool_result",
              "content": [{"type": "text", "text": "ok"}]}
         ]}},
        {"type": "assistant", "sessionId": "abc",
         "timestamp": "2026-05-07T10:02:00Z",
         "message": {"content": [{"type": "text", "text": "Done."}]}},
    ])

    digest = parse_transcript(transcript)

    assert isinstance(digest, SessionDigest)
    assert digest.session_id == "abc"
    assert digest.user_turn_count == 2
    assert digest.assistant_turn_count == 2
    assert digest.started_at == "2026-05-07T10:00:00Z"
    assert digest.ended_at == "2026-05-07T10:02:00Z"
    assert digest.head[0].text == "First user prompt"
    # Final exchanges should include the last assistant turn.
    assert any("Done." in t.text for t in digest.tail)


def test_parse_skips_tool_use_in_text_extraction(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "assistant", "sessionId": "x",
         "message": {"content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": "/x"}},
             {"type": "text", "text": "Reading that file."},
         ]}},
    ])
    digest = parse_transcript(transcript)
    assert digest.tail[-1].text == "Reading that file."


def test_parse_handles_malformed_lines(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"type":"user","message":{"content":"ok"}}\n'
        "this is not json\n"
        '{"type":"assistant","message":{"content":"reply"}}\n',
        encoding="utf-8",
    )
    digest = parse_transcript(transcript)
    assert digest.user_turn_count == 1
    assert digest.assistant_turn_count == 1


def test_excerpt_caps_long_turns(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "sessionId": "x",
         "message": {"content": "A" * 20_000}},
    ])
    digest = parse_transcript(transcript)
    excerpt = digest.as_excerpt(turn_char_limit=500)
    assert "[…truncated" in excerpt
    assert len(excerpt) < 2_000


def test_derive_cwd_from_dirname() -> None:
    p = Path("~/.claude/projects/-Users-you-foo-bar/abc.jsonl")
    assert derive_cwd_from_dirname(p) == "/Users/you/foo/bar"


def test_derive_cwd_returns_none_when_not_encoded() -> None:
    p = Path("/tmp/session.jsonl")
    assert derive_cwd_from_dirname(p) is None
