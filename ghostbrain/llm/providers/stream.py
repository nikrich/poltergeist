"""Stream a CLI subprocess's stdout as renderer events with the same lifecycle
guarantees `agent.run_chat_turn` had before this module existed: own process
group, watchdog timeout, cancel via the shared turn registry, kill-group on
exit, stderr capture on failure.

This is Claude-chat-specific in its cancelled/timeout wording (matches the
"poltergeist"-branded copy `run_chat_turn` has always shown users) — not yet
generalized for other providers, since only the Claude adapter uses it today.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator

from ghostbrain.llm.providers import base


def stream_subprocess(
    cmd: list[str],
    *,
    timeout_s: int,
    turn_key: str | None,
    parse: Callable[[str], list[dict]],
    on_exit: Callable[[int, str, bool], list[dict]],
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
    cwd: str | None = None,
) -> Iterator[dict]:
    """Run ``cmd``, yielding ``parse(line)`` events for each stdout line.

    Registers ``turn_key`` (if given) in the shared turn registry so an
    external caller can cancel the subprocess via ``base.cancel_turn`` while
    this generator is suspended at a ``yield``. A watchdog timer kills the
    process group after ``timeout_s`` with no terminal ("done"/"error")
    event seen. On normal EOF with no terminal event, ``on_exit(returncode,
    stderr_tail, saw_any)`` supplies the closing event(s) — it may also raise
    (e.g. the Claude adapter's ``ResumeFailed``).
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env={**os.environ, **(env or {})},
        cwd=cwd,
        # Own process group: the CLI spawns descendants (MCP servers, tool
        # subprocesses) that inherit the stdout pipe write-end — killing only
        # the direct child would leave the pipe open and our read loop
        # blocked until the orphans exit. Group-kill (below) takes them all.
        start_new_session=True,
    )
    if stdin_text is not None:
        assert proc.stdin is not None
        proc.stdin.write(stdin_text)
        proc.stdin.close()

    def _kill_group() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # already gone
        except Exception:  # noqa: BLE001 — cleanup must never raise past us
            proc.kill()

    timed_out = threading.Event()
    cancelled = threading.Event()

    def _on_timeout() -> None:
        timed_out.set()
        _kill_group()

    # Register this turn before starting the watchdog so an external caller
    # can reach it (via base.cancel_turn) as soon as this generator first
    # suspends at a yield — GeneratorExit alone can't interrupt a generator
    # blocked reading from the subprocess.
    if turn_key is not None:
        base.register_turn(turn_key, cancelled=cancelled, kill=_kill_group)

    killer = threading.Timer(timeout_s, _on_timeout)
    killer.start()
    saw_any = False
    saw_terminal = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            for event in parse(raw):
                saw_any = True
                if event["type"] in ("done", "error"):
                    saw_terminal = True
                yield event
        proc.wait()
    finally:
        # Covers normal exit, timeout, and client-disconnect (GeneratorExit
        # propagates here when the caller stops consuming) — never leave a
        # live subprocess group behind.
        killer.cancel()
        if proc.poll() is None:
            _kill_group()
            proc.wait()
        if turn_key is not None:
            base.unregister_turn(turn_key)

    if saw_terminal:
        return

    stderr_tail = (proc.stderr.read() if proc.stderr else "")[:500].strip()

    # cancelled is checked FIRST: a cancelled turn that died before any
    # output must not be misclassified as a resume failure (which would
    # trigger a pointless retry in the Claude adapter).
    if cancelled.is_set():
        yield {"type": "error", "message": "stopped", "interrupted": True}
        return
    if timed_out.is_set():
        yield {
            "type": "error",
            "message": f"poltergeist took longer than {timeout_s}s and was stopped.",
            "interrupted": True,
        }
        return
    yield from on_exit(proc.returncode, stderr_tail, saw_any)
