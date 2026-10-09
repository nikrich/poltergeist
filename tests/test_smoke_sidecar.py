"""scripts/smoke-sidecar.py MCP handshake against stub "binaries".

The real `ghostbrain-api mcp` server (mcp>=1.x Server.run) cancels in-flight
request handlers as soon as stdin hits EOF. The smoke check used to write
initialize + initialized + tools/list and close stdin in one go, so on a fast
EOF the tools/list response was never written ("missing tools: got []").
These stubs reproduce that server behaviour deterministically.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="stub binaries rely on a POSIX shebang"
)

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke-sidecar.py"

# Answers initialize at once, answers tools/list only after a delay, and exits
# on stdin EOF without answering pending requests — like the real server.
_DELAYED_SERVER = """
import json, os, sys, threading

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def answer_tools(req_id):
    send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
        {"name": "poltergeist_ask"},
        {"name": "poltergeist_search"},
        {"name": "poltergeist_get_note"},
        {"name": "poltergeist_write_doc"},
    ]}})

for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
    elif msg.get("method") == "tools/list":
        threading.Timer(0.5, answer_tools, args=(msg["id"],)).start()
sys.stderr.write("stdin closed, dropping in-flight requests\\n")
sys.stderr.flush()
os._exit(0)
"""

# Answers initialize, then dies on tools/list without answering it.
_CRASHING_SERVER = """
import json, os, sys

line = sys.stdin.readline()
msg = json.loads(line)
sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {}}) + "\\n")
sys.stdout.flush()
while json.loads(sys.stdin.readline()).get("method") != "tools/list":
    pass
sys.stderr.write("Traceback: boom in tools/list\\n")
sys.stderr.flush()
os._exit(3)
"""


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_sidecar", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub(tmp_path: Path, body: str) -> str:
    binary = tmp_path / "ghostbrain-api"
    binary.write_text(f"#!{sys.executable}\n{body}")
    binary.chmod(0o755)
    return str(binary)


def test_handshake_waits_for_tools_list_before_closing_stdin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    smoke = _load_smoke()
    binary = _stub(tmp_path, _DELAYED_SERVER)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    smoke.check_mcp_handshake(binary, sandbox)

    assert "initialize + tools/list (4 tools)" in capsys.readouterr().out


def test_handshake_failure_reports_binary_stderr(tmp_path: Path) -> None:
    smoke = _load_smoke()
    binary = _stub(tmp_path, _CRASHING_SERVER)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    with pytest.raises(SystemExit) as exc:
        smoke.check_mcp_handshake(binary, sandbox)

    message = str(exc.value)
    assert "missing tools" in message
    assert "boom in tools/list" in message
