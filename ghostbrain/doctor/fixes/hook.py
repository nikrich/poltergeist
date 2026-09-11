"""`setup install-hook` — wire Claude Code's SessionEnd hook to this binary."""
from __future__ import annotations

import sys

from ghostbrain.api import claude_settings
from ghostbrain.doctor.fixes.cli_shim import binary_path

POLTERGEIST_MARKERS = ("session-end", "ghostbrain-api", "poltergeist")


def hook_command() -> str:
    return f'"{binary_path()}" session-end'


def _is_ours(command: str) -> bool:
    return any(m in command for m in POLTERGEIST_MARKERS)


def install(doc: dict, command: str) -> dict:
    hooks = doc.setdefault("hooks", {})
    entries = hooks.get("SessionEnd") or []
    kept: list[dict] = []
    present = False
    for entry in entries:
        cmds = [h.get("command", "") for h in entry.get("hooks") or []]
        if command in cmds:
            present = True
            kept.append(entry)
            continue
        stale = any(_is_ours(c) and not claude_settings.hook_command_exists(c) for c in cmds)
        if not stale:
            kept.append(entry)
    if not present:
        kept.append({"matcher": "*", "hooks": [{"type": "command", "command": command, "async": True}]})
    hooks["SessionEnd"] = kept
    return doc


def main(argv: list[str] | None = None) -> int:
    try:
        doc = claude_settings.load()
    except ValueError as e:
        print(f"~/.claude/settings.json is not valid JSON ({e}); fix it by hand first", file=sys.stderr)
        return 1
    command = hook_command()
    before = claude_settings.session_end_commands(doc)
    doc = install(doc, command)
    after = claude_settings.session_end_commands(doc)
    if before == after:
        print(f"SessionEnd hook already installed: {command}")
        return 0
    claude_settings.write_atomic(doc)
    print(f"SessionEnd hook installed in {claude_settings.settings_path()}: {command}")
    return 0
