"""`setup go-live` — flip worker.routing_mode to live, preserving the file's comments."""
from __future__ import annotations

import re
import sys

from ghostbrain.paths import vault_path

_WORKER_HEADER = re.compile(r"^worker:\s*$")
_MODE_LINE = re.compile(r"^(\s*)routing_mode:\s*\S+")


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = vault_path() / "90-meta" / "config.yaml"
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""

        lines = text.splitlines(keepends=True)

        # Find the worker: header line
        header_idx = None
        for i, line in enumerate(lines):
            if _WORKER_HEADER.match(line):
                header_idx = i
                break

        if header_idx is not None:
            # Find the end of the worker block (first line that doesn't start with space or #)
            end_idx = len(lines)
            for i in range(header_idx + 1, len(lines)):
                line = lines[i]
                if line and line[0] not in (" ", "#", "\n"):
                    end_idx = i
                    break

            # Check if routing_mode already exists in the block
            mode_idx = None
            for i in range(header_idx + 1, end_idx):
                if _MODE_LINE.match(lines[i]):
                    mode_idx = i
                    break

            if mode_idx is not None:
                # Replace the existing routing_mode line
                match = _MODE_LINE.match(lines[mode_idx])
                indent = match.group(1)
                newline = "\n" if lines[mode_idx].endswith("\n") else ""
                new_line = f"{indent}routing_mode: live{newline}"
                if lines[mode_idx] != new_line:
                    lines[mode_idx] = new_line
            else:
                # Insert routing_mode after the header
                lines.insert(header_idx + 1, "  routing_mode: live\n")
        else:
            # No worker block; append one
            if text and not text.endswith("\n"):
                text += "\n"
            if text.strip():
                text += "\n"
            text += "worker:\n  routing_mode: live\n"
            lines = text.splitlines(keepends=True)

        new = "".join(lines)

        if new != text:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(new, encoding="utf-8")
            print(f"routing_mode set to live in {cfg}")
        else:
            print("routing_mode is already live")

        inbox = vault_path() / "00-inbox" / "raw"
        count = len(list(inbox.glob("*.md"))) if inbox.exists() else 0
        print(f"{count} item(s) in 00-inbox/raw will be filed on the worker's next pass")
        return 0
    except OSError as e:
        print(f"go-live failed: {e}", file=sys.stderr)
        return 1
