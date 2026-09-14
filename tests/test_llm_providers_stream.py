"""stream_subprocess lifecycle guarantees that are not provider-specific."""
from __future__ import annotations

import stat
import time
from pathlib import Path

from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.stream import stream_subprocess


def _script(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake-cli"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def test_stdin_write_to_a_child_that_exited_does_not_leak_the_turn(tmp_path: Path):
    """The stdin write used to sit ABOVE the try/finally: a child that exits
    before reading (a CLI that rejects its flags) makes the write raise
    BrokenPipeError, and the turn was then never killed or unregistered — the
    conversation stayed "busy" forever with no way to cancel it."""
    cmd = [_script(tmp_path, "exit 3\n")]
    # Bigger than a pipe buffer, so the write cannot quietly succeed.
    payload = "x" * (1024 * 1024)
    events = list(stream_subprocess(
        cmd, timeout_s=10, turn_key="stdin-1", stdin_text=payload,
        parse=lambda line: [],
        on_exit=lambda rc, err, saw: [{"type": "error", "message": f"exited {rc}"}],
    ))
    assert events == [{"type": "error", "message": "exited 3"}]
    # Unregistered: nothing left in the turn registry to cancel.
    assert base.cancel_turn("stdin-1") is False


def test_stdin_is_delivered_to_a_child_that_reads_it(tmp_path: Path):
    cmd = [_script(tmp_path, 'cat\n')]
    events = list(stream_subprocess(
        cmd, timeout_s=10, turn_key=None, stdin_text='{"type":"hello"}\n',
        parse=lambda line: [{"type": "delta", "text": line.strip()}] if line.strip() else [],
        on_exit=lambda rc, err, saw: [{"type": "done", "text": "", "session_id": ""}],
    ))
    assert {"type": "delta", "text": '{"type":"hello"}'} in events


def test_large_stdin_does_not_deadlock_against_a_chatty_child(tmp_path: Path):
    """Writing stdin inline blocks once the pipe buffer fills, while the child
    blocks writing stdout that nobody is reading yet. Feeding stdin from a
    helper thread keeps both sides moving."""
    cmd = [_script(tmp_path, 'yes chatter | head -c 200000\ncat > /dev/null\n')]
    start = time.monotonic()
    events = list(stream_subprocess(
        cmd, timeout_s=20, turn_key=None, stdin_text="y" * (1024 * 1024),
        parse=lambda line: [],
        on_exit=lambda rc, err, saw: [{"type": "done", "text": "", "session_id": ""}],
    ))
    assert events[-1]["type"] == "done"
    assert time.monotonic() - start < 15
