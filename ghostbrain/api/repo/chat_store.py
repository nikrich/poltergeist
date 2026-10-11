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
from typing import Callable

from ghostbrain.paths import chats_dir

log = logging.getLogger("ghostbrain.chat.store")

TITLE_MAX_LEN = 60

lock = threading.RLock()  # every read-modify-write of chat files + folders.json

LOCATION_FIELDS = ("context", "project", "folder", "auto_filed")
AUTO_FILE_STATES = ("pending", "done", "skipped")


def normalize(conv: dict) -> dict:
    """Bring any stored shape up to the current one (mutates + returns).

    Legacy files hold ``project: "ctx/slug"`` and no context/folder/auto_filed.
    They predate auto-filing, so they read as ``skipped`` and are never routed.
    """
    project = conv.get("project")
    if project and not conv.get("context"):
        ctx, sep, slug = str(project).partition("/")
        if sep and ctx:
            conv["context"], conv["project"] = ctx, (slug or None)
        else:
            conv["project"] = None
    if not conv.get("context"):
        conv["context"] = None
        conv["project"] = None
        conv["folder"] = None
    conv.setdefault("project", None)
    conv["folder"] = conv.get("folder") or None
    if conv.get("auto_filed") not in AUTO_FILE_STATES:
        conv["auto_filed"] = "skipped"
    return conv


RESERVED_FILES = frozenset({"folders.json"})  # chat_folders' registry shares the dir


def _chat_files(d: Path) -> list[Path]:
    return [p for p in d.glob("*.json") if p.name not in RESERVED_FILES]


def _conv_path(conv_id: str) -> Path:
    return chats_dir() / f"{conv_id}.json"


def _read_raw(conv_id: str) -> dict | None:
    path = _conv_path(conv_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        log.warning("unreadable conversation file: %s", path)
        return None


def _write(conv: dict) -> None:
    d = chats_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _conv_path(conv["id"])
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _write_turn(conv: dict) -> None:
    """Persist a turn-path write without clobbering a concurrent move.

    The stream handler holds its own dict for the whole turn; location fields
    are owned by move()/apply_auto_file(), so they're re-read from disk here.
    A conversation deleted mid-turn is re-created (pre-existing behaviour).
    """
    with lock:
        disk = _read_raw(conv["id"])
        if disk is not None:
            normalize(disk)
            for f in LOCATION_FIELDS:
                conv[f] = disk[f]
        _write(conv)


def derive_title(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:TITLE_MAX_LEN] or "new chat"


def _newest_empty() -> dict | None:
    d = chats_dir()
    if not d.exists():
        return None
    best: dict | None = None
    for p in _chat_files(d):
        try:
            conv = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if conv.get("messages"):
            continue
        normalize(conv)
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
    with lock:
        existing = _newest_empty()
        if existing is not None:
            if not existing["context"] and existing["auto_filed"] != "pending":
                existing["auto_filed"] = "pending"
                _write(existing)
            return existing
        now = time.time()
        conv = {
            "id": uuid.uuid4().hex,
            "title": "new chat",
            "created_at": now,
            "updated_at": now,
            "claude_session_id": None,
            "context": None,
            "project": None,
            "folder": None,
            "auto_filed": "pending",
            "messages": [],
        }
        _write(conv)
        return conv


def get(conv_id: str) -> dict | None:
    conv = _read_raw(conv_id)
    return normalize(conv) if conv is not None else None


def iter_all() -> list[dict]:
    """All readable conversations, normalized, full bodies, unsorted."""
    d = chats_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in _chat_files(d):
        try:
            conv = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("skipping unreadable conversation file: %s", p)
            continue
        out.append(normalize(conv))
    return out


def list_all() -> list[dict]:
    """Conversation summaries (no message bodies), newest-updated first."""
    out = [
        {
            "id": conv["id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "message_count": len(conv.get("messages", [])),
            "context": conv["context"],
            "project": conv["project"],
            "folder": conv["folder"],
            "auto_filed": conv["auto_filed"],
        }
        for conv in iter_all()
    ]
    out.sort(key=lambda c: c["updated_at"], reverse=True)
    return out


_UNSET = object()


def update(conv_id: str, *, title=_UNSET) -> dict | None:
    """Partial update: only passed fields change."""
    with lock:
        conv = get(conv_id)
        if conv is None:
            return None
        if title is not _UNSET:
            conv["title"] = str(title).strip()[:TITLE_MAX_LEN]
        conv["updated_at"] = time.time()
        _write(conv)
        return conv


def move(
    conv_id: str, *, context: str | None, project: str | None, folder: str | None
) -> dict | None:
    """Set a chat's location. No validation (chat_folders does that). A manual
    move always ends auto-filing, and doesn't count as activity (updated_at)."""
    with lock:
        conv = get(conv_id)
        if conv is None:
            return None
        if context is None:
            project = folder = None
        conv.update(context=context, project=project, folder=folder or None, auto_filed="done")
        _write(conv)
        return conv


def apply_auto_file(conv_id: str, context: str | None, project: str | None) -> dict | None:
    """Land a router decision — only if the chat is still waiting for one."""
    with lock:
        conv = get(conv_id)
        if conv is None or conv["auto_filed"] != "pending":
            return None
        if context:
            conv.update(context=context, project=project, folder=None)
        conv["auto_filed"] = "done"
        _write(conv)
        return conv


def rewrite_all(fn: Callable[[dict], bool]) -> int:
    """Apply ``fn`` to every readable chat under the lock; write those it flags."""
    n = 0
    with lock:
        d = chats_dir()
        if not d.exists():
            return 0
        for p in list(_chat_files(d)):
            conv = _read_raw(p.stem)
            if conv is None:
                continue
            normalize(conv)
            if fn(conv):
                _write(conv)
                n += 1
    return n


def rename(conv_id: str, title: str) -> dict | None:
    return update(conv_id, title=title)


def delete(conv_id: str) -> bool:
    with lock:
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
    _write_turn(conv)
    return conv


def append_assistant_message(
    conv: dict, text: str, tools: list[dict], *, interrupted: bool = False
) -> dict:
    conv["messages"].append(
        {"role": "assistant", "text": text, "tools": tools, "interrupted": interrupted}
    )
    conv["updated_at"] = time.time()
    _write_turn(conv)
    return conv


def set_session_id(conv: dict, session_id: str, provider: str | None = None) -> dict:
    """Record the CLI session id and which provider minted it.

    Session ids are per provider — a claude uuid means nothing to `codex exec
    resume` or `gemini --resume` — so the owning provider is stored alongside
    it and read back by repo/chat.py before any resume is attempted. Omitting
    ``provider`` leaves whatever is already recorded (conversations written
    before this field existed can only hold a claude session).
    """
    conv["claude_session_id"] = session_id
    if provider is not None:
        conv["session_provider"] = provider
    _write_turn(conv)
    return conv
