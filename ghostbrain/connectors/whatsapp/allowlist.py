"""Opt-in chat allowlist: state/whatsapp.allowed_chats.json."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.whatsapp.allowlist")

FILENAME = "whatsapp.allowed_chats.json"


def load(state_dir: Path) -> dict[str, dict]:
    f = state_dir / FILENAME
    if not f.exists():
        return {}
    try:
        return dict(json.loads(f.read_text(encoding="utf-8")).get("chats") or {})
    except (ValueError, AttributeError):
        log.warning("ignoring unreadable %s", f)
        return {}


def save(state_dir: Path, chats: dict[str, dict]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / FILENAME
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"chats": chats}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
