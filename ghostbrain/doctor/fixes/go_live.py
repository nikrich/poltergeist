"""`setup go-live` — flip worker.routing_mode to live, preserving the file's comments."""
from __future__ import annotations

import re
import sys

from ghostbrain.paths import vault_path

_WORKER_HEADER = re.compile(r"^worker:\s*$", re.MULTILINE)
_MODE_LINE = re.compile(r"^(\s*)routing_mode:\s*\S+.*$", re.MULTILINE)


def _extract_worker_block(text: str) -> tuple[str, str, str]:
    """Extract (before, worker_block, after) for the worker block in YAML text.

    If no worker block exists, returns (text, "", "").
    """
    match = _WORKER_HEADER.search(text)
    if not match:
        return text, "", ""

    start = match.start()
    # Find the end of the worker block: next line that starts with non-space or EOF
    after_header = match.end()
    lines = text[after_header:].split("\n")
    block_lines = []
    rest_start = after_header

    for i, line in enumerate(lines):
        if i == 0:  # The first line after "worker:" is empty or continuation
            block_lines.append(line)
            rest_start = after_header + len(line) + 1
        elif line and not line[0].isspace() and line[0] != "#":
            # This line is at the start of a new block, so it's not part of worker
            rest_start = after_header + sum(len(l) + 1 for l in lines[:i])
            break
        else:
            block_lines.append(line)
            rest_start = after_header + sum(len(l) + 1 for l in lines[: i + 1])

    before = text[:start]
    worker_block = "worker:" + "\n" + "\n".join(block_lines)
    after = text[rest_start - 1:] if rest_start > after_header else ""

    return before, worker_block, after


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = vault_path() / "90-meta" / "config.yaml"
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""

        before, worker_block, after = _extract_worker_block(text)

        if worker_block:
            # Worker block exists; check if it has routing_mode
            if _MODE_LINE.search(worker_block):
                new_block = _MODE_LINE.sub(lambda m: f"{m.group(1)}routing_mode: live", worker_block, count=1)
            else:
                # Add routing_mode after "worker:" header
                new_block = "worker:\n  routing_mode: live" + worker_block[7:]  # 7 = len("worker:")
            new = before + new_block + after
        else:
            # No worker block; append one
            new = text.rstrip("\n") + ("\n\n" if text.strip() else "") + "worker:\n  routing_mode: live\n"

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
