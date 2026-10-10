#!/usr/bin/env python3
"""Smoke-test the frozen sidecar binary after a PyInstaller build.

CI builds the binary but historically never ran it, which shipped two
dead-on-arrival regressions (v1.0.0 pkg_resources crash, every release
through v1.3.1 with a broken `mcp` subcommand). This runs the actual
artifact both ways:

  1. server mode — must print "READY port=... token=..." on stdout
  2. `mcp` subcommand — must answer an MCP initialize + tools/list
     handshake with the three poltergeist tools

Usage: python scripts/smoke-sidecar.py <path-to-ghostbrain-api-binary>
Exits non-zero (with the binary's stderr) on any failure.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _env(tmp: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GHOSTBRAIN_STATE_DIR"] = str(tmp / "state")
    env["VAULT_PATH"] = str(tmp / "vault")
    # The sidecar writes ~/ghostbrain/run/sidecar.json regardless of
    # GHOSTBRAIN_STATE_DIR. Point HOME at the sandbox too, or a local smoke
    # run clobbers the real app's port/token pointer and every MCP client
    # starts failing with "Poltergeist isn't running".
    env["HOME"] = str(tmp)
    env["USERPROFILE"] = str(tmp)  # Windows equivalent
    return env


def check_server_ready(binary: str, tmp: Path) -> None:
    proc = subprocess.Popen(
        [binary],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp),
    )
    try:
        deadline = time.monotonic() + 120
        line = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                _, err = proc.communicate()
                raise SystemExit(
                    f"sidecar exited (code={proc.returncode}) before READY:\n{err[-2000:]}"
                )
            line = proc.stdout.readline() if proc.stdout else ""
            if "READY port=" in line:
                print(f"server mode: {line.strip().split(' token=')[0]} … OK")
                return
        raise SystemExit("sidecar never printed READY within 120s")
    finally:
        proc.kill()
        proc.wait()


def _send(proc: subprocess.Popen[str], message: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def _drain(stream, sink) -> None:
    """Pump a pipe from a thread: a portable stand-in for select() on pipes,
    which Windows runners don't support."""
    for line in stream:
        sink(line)


def check_mcp_handshake(binary: str, tmp: Path, timeout: float = 120) -> None:
    # Strictly request/response: the mcp server cancels in-flight handlers as
    # soon as stdin hits EOF, so closing stdin right after writing tools/list
    # races the handler and intermittently drops its response (v1.11.0 Linux
    # release flake: "missing tools: got []"). Only close stdin once every
    # response we need has arrived.
    proc = subprocess.Popen(
        [binary, "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp),
    )
    lines: queue.Queue[str | None] = queue.Queue()
    stderr: list[str] = []

    def pump_stdout() -> None:
        _drain(proc.stdout, lines.put)
        lines.put(None)

    readers = [
        threading.Thread(target=pump_stdout, daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, stderr.append), daemon=True),
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout

    def stop(grace: float) -> None:
        # Closing stdin is the server's shutdown signal; kill it if it lingers.
        with contextlib.suppress(OSError):
            proc.stdin.close()
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for reader in readers:
            reader.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()

    def fail(reason: str) -> SystemExit:
        stop(grace=0)
        return SystemExit(
            f"{reason} (exit code={proc.returncode}). stderr:\n{''.join(stderr)[-2000:]}"
        )

    def response(req_id: int) -> dict | None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise fail(f"mcp handshake timed out after {timeout:.0f}s")
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if raw is None:
                return None  # stdout closed: the binary exited
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == req_id:
                return msg

    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
        )
        init = response(1)
        if not init or "result" not in init:
            raise fail(f"mcp initialize got no result: {init}")
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = response(2)
    except OSError as exc:  # broken pipe: the binary died mid-handshake
        raise fail(f"mcp handshake write failed: {exc}") from None

    tools = [t["name"] for t in ((listed or {}).get("result") or {}).get("tools", [])]
    expected = {"poltergeist_ask", "poltergeist_search", "poltergeist_get_note"}
    if not expected.issubset(tools):
        raise fail(f"mcp tools/list missing tools: got {tools} (response: {listed})")

    stop(grace=10)
    print(f"mcp subcommand: initialize + tools/list ({len(tools)} tools) … OK")


def check_ontology_selfcheck(binary: str, tmp: str) -> None:
    proc = subprocess.run([binary, "ontology-selfcheck"], env=_env(Path(tmp)), capture_output=True,
                          text=True, timeout=240, cwd=tmp)
    if proc.returncode != 0 or "ontology selfcheck: OK" not in proc.stdout:
        raise SystemExit(f"ontology selfcheck failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    if (Path(tmp) / "log").exists():
        raise SystemExit("ontology selfcheck leaked a ./log directory into the process cwd")
    print("ontology selfcheck: OK")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke-sidecar.py <path-to-ghostbrain-api-binary>")
    # Absolute: the ontology self-check runs with cwd=<tmp>, where a relative
    # path to the binary no longer resolves.
    binary = str(Path(sys.argv[1]).resolve())
    if not Path(binary).exists():
        raise SystemExit(f"binary not found: {binary}")
    with tempfile.TemporaryDirectory() as tmp:
        check_server_ready(binary, Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        check_mcp_handshake(binary, Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        check_ontology_selfcheck(binary, tmp)
    print("sidecar smoke test: PASS")


if __name__ == "__main__":
    main()
