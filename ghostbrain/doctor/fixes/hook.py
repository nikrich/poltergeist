"""`setup install-hook` — wire Claude Code's SessionEnd hook to this binary."""
from __future__ import annotations

import shlex
import sys

from ghostbrain.api import claude_settings
from ghostbrain.doctor.fixes.cli_shim import binary_argv


def hook_command() -> str:
    return shlex.join([*binary_argv(), "session-end"])


def _is_ours(command: str) -> bool:
    """True only for a command this tool could plausibly have installed.

    Deliberately narrow: a bare "poltergeist" or "session-end" substring
    marker matched too much (a user's own `/home/me/poltergeist/notes.sh` or
    `/some/tool/session-end.sh` hook), so `install-hook` could delete a
    third-party hook it didn't own. "Ours" now requires the command's last
    shlex token to be the literal `session-end` subcommand AND the command to
    reference `ghostbrain-api` or `ghostbrain.api` somewhere.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens or tokens[-1] != "session-end":
        return False
    return any("ghostbrain-api" in t or "ghostbrain.api" in t for t in tokens)


def install(doc: dict, command: str) -> dict:
    hooks = doc.setdefault("hooks", {})
    entries = hooks.get("SessionEnd") or []
    kept: list[dict] = []
    present = False
    for entry in entries:
        entry_hooks = entry.get("hooks") or []
        kept_hooks: list[dict] = []
        for h in entry_hooks:
            cmd = h.get("command", "")
            if cmd == command:
                present = True
                kept_hooks.append(h)
                continue
            if _is_ours(cmd) and not claude_settings.hook_command_exists(cmd):
                continue  # stale command of ours — drop just this one
            kept_hooks.append(h)
        if not kept_hooks:
            continue  # entry emptied out by pruning — drop the whole entry
        if kept_hooks != entry_hooks:
            entry = {**entry, "hooks": kept_hooks}
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
