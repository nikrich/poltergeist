"""JSON-file-per-conversation storage for poltergeist chat.

One file per conversation at ``chats_dir()/<id>.json``. Files are the source
of truth — no DB, no cache. Writes are atomic (tmp + rename) so a crash
mid-write never corrupts a conversation. Corrupt files are skipped on list
and read as missing on get; chat must keep working even if one file rots.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from ghostbrain.paths import chats_dir

log = logging.getLogger("ghostbrain.chat.store")

TITLE_MAX_LEN = 60

_create_lock = threading.Lock()


def _conv_path(conv_id: str) -> Path:
    return chats_dir() / f"{conv_id}.json"


def _write(conv: dict) -> None:
    d = chats_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _conv_path(conv["id"])
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def derive_title(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:TITLE_MAX_LEN] or "new chat"


def _newest_empty() -> dict | None:
    d = chats_dir()
    if not d.exists():
        return None
    best: dict | None = None
    for p in d.glob("*.json"):
        try:
            conv = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if conv.get("messages"):
            continue
        if best is None or conv.get("created_at", 0) > best.get("created_at", 0):
            best = conv
    return best


def create() -> dict:
    """Return an empty conversation — reusing one that already exists.

    "new chat" clicks can arrive several times before the UI disables the
    button (isPending flips a render later), and abandoned empties otherwise
    pile up in the sidebar forever. Idempotent create fixes both: as long as
    an unused conversation exists, that's the one you get.
    """
    with _create_lock:
        existing = _newest_empty()
        if existing is not None:
            return existing
        now = time.time()
        conv = {
            "id": uuid.uuid4().hex,
            "title": "new chat",
            "created_at": now,
            "updated_at": now,
            "claude_session_id": None,
            "project": None,
            "messages": [],
        }
        _write(conv)
        return conv


def get(conv_id: str) -> dict | None:
    path = _conv_path(conv_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        log.warning("unreadable conversation file: %s", path)
        return None


def list_all() -> list[dict]:
    """Conversation summaries (no message bodies), newest-updated first."""
    d = chats_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in d.glob("*.json"):
        try:
            conv = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("skipping unreadable conversation file: %s", p)
            continue
        out.append(
            {
                "id": conv["id"],
                "title": conv["title"],
                "created_at": conv["created_at"],
                "updated_at": conv["updated_at"],
                "message_count": len(conv.get("messages", [])),
                "project": conv.get("project"),
            }
        )
    out.sort(key=lambda c: c["updated_at"], reverse=True)
    return out


_UNSET = object()


def update(conv_id: str, *, title=_UNSET, project=_UNSET) -> dict | None:
    """Partial update: only passed fields change. project=None unfiles."""
    conv = get(conv_id)
    if conv is None:
        return None
    if title is not _UNSET:
        conv["title"] = str(title).strip()[:TITLE_MAX_LEN]
    if project is not _UNSET:
        conv["project"] = project
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def rename(conv_id: str, title: str) -> dict | None:
    return update(conv_id, title=title)


def delete(conv_id: str) -> bool:
    path = _conv_path(conv_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def append_user_message(
    conv: dict, text: str, *, attachments: list[dict] | None = None
) -> dict:
    msg: dict = {"role": "user", "text": text}
    if attachments:
        msg["attachments"] = attachments
    conv["messages"].append(msg)
    if len(conv["messages"]) == 1:
        conv["title"] = derive_title(text)
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def append_assistant_message(
    conv: dict, text: str, tools: list[dict], *, interrupted: bool = False
) -> dict:
    conv["messages"].append(
        {"role": "assistant", "text": text, "tools": tools, "interrupted": interrupted}
    )
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def set_session_id(conv: dict, session_id: str) -> dict:
    conv["claude_session_id"] = session_id
    _write(conv)
    return conv
