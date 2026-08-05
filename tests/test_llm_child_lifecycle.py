"""Spawned `claude` children must die with their process group.

The 2026-08-04 incident: an orphaned `claude -p` tick outlived its parent
and spun at ~100% CPU for three weeks, starving every other session on the
account via rate limits. Two invariants guard against the class:

- `client._run_once` timeout kills the WHOLE process group, not just the
  direct child (claude spawns MCP-server/tool grandchildren).
- `agent.kill_all_running()` reaps every in-flight chat turn; the sidecar
  calls it on shutdown so an app quit can't orphan turns.
"""
from __future__ import annotations

import os
import signal
import stat
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ghostbrain.llm import agent, client


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_run_once_timeout_kills_grandchildren(tmp_path: Path) -> None:
    """A fake claude spawns a grandchild, writes its pid, then hangs. After
    the timeout both generations must be dead."""
    pid_file = tmp_path / "grandchild.pid"
    fake = tmp_path / "fake-claude.sh"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            sleep 300 &
            echo $! > {pid_file}
            wait
            """
        )
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    with pytest.raises(client.LLMTimeout):
        client._run_once([str(fake)], timeout_s=1)

    deadline = time.monotonic() + 5
    grandchild = int(pid_file.read_text().strip())
    while time.monotonic() < deadline and _alive(grandchild):
        time.sleep(0.1)
    assert not _alive(grandchild), "grandchild survived the group kill"


def test_kill_all_running_reaps_registered_turns() -> None:
    killed = threading.Event()
    with agent._running_lock:
        agent._running["test-turn"] = agent._RunningTurn(
            cancelled=threading.Event(), kill=killed.set
        )
    try:
        reaped = agent.kill_all_running()
    finally:
        with agent._running_lock:
            agent._running.pop("test-turn", None)
    assert reaped >= 1
    assert killed.is_set()
    with agent._running_lock:
        assert "test-turn" not in agent._running
