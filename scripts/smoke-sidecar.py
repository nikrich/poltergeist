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

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _env(tmp: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GHOSTBRAIN_STATE_DIR"] = str(tmp / "state")
    env["VAULT_PATH"] = str(tmp / "vault")
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


def check_mcp_handshake(binary: str, tmp: Path) -> None:
    requests = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    proc = subprocess.Popen(
        [binary, "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp),
    )
    try:
        out, err = proc.communicate(input=requests, timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit(f"mcp handshake timed out. stderr:\n{err[-2000:]}")

    tools: list[str] = []
    initialized = False
    for raw in out.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 1 and "result" in msg:
            initialized = True
        if msg.get("id") == 2 and "result" in msg:
            tools = [t["name"] for t in msg["result"].get("tools", [])]

    if not initialized:
        raise SystemExit(f"mcp initialize got no result. stderr:\n{err[-2000:]}")
    expected = {"poltergeist_ask", "poltergeist_search", "poltergeist_get_note"}
    if not expected.issubset(tools):
        raise SystemExit(f"mcp tools/list missing tools: got {tools}")
    print(f"mcp subcommand: initialize + tools/list ({len(tools)} tools) … OK")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke-sidecar.py <path-to-ghostbrain-api-binary>")
    binary = sys.argv[1]
    if not Path(binary).exists():
        raise SystemExit(f"binary not found: {binary}")
    with tempfile.TemporaryDirectory() as tmp:
        check_server_ready(binary, Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        check_mcp_handshake(binary, Path(tmp))
    print("sidecar smoke test: PASS")


if __name__ == "__main__":
    main()
