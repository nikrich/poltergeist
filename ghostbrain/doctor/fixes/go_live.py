"""`setup go-live` — flip worker.routing_mode to live, preserving the file's comments."""
from __future__ import annotations

import re

from ghostbrain.paths import vault_path

_MODE_LINE = re.compile(r"^(\s*)routing_mode:\s*\S+.*$", re.MULTILINE)
_WORKER_HEADER = re.compile(r"^worker:\s*$", re.MULTILINE)


def main(argv: list[str] | None = None) -> int:
    cfg = vault_path() / "90-meta" / "config.yaml"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if _MODE_LINE.search(text):
        new = _MODE_LINE.sub(lambda m: f"{m.group(1)}routing_mode: live", text, count=1)
    elif _WORKER_HEADER.search(text):
        new = _WORKER_HEADER.sub("worker:\n  routing_mode: live", text, count=1)
    else:
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
