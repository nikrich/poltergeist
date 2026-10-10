"""GET/PUT /v1/connectors/whatsapp/chats — the opt-in chat picker's backend."""
from __future__ import annotations

import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ghostbrain import routing_config
from ghostbrain.connectors.whatsapp import allowlist, store
from ghostbrain.paths import state_dir

router = APIRouter(prefix="/v1/connectors/whatsapp", tags=["connectors"])

ACCESS_HINT = ("Poltergeist can't read WhatsApp's data. Grant it Full Disk Access in "
               "System Settings → Privacy & Security → Full Disk Access, then retry.")


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool
    context: str | None = None


class ChatsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chats: dict[str, ChatChoice]


def _chats() -> list[store.Chat]:
    path = store.default_store_path()
    try:
        with closing(store.open_store(path)) as conn:
            store.check_schema(conn)
            return store.list_chats(conn, tz=store.local_tz())
    except FileNotFoundError as e:
        raise HTTPException(status_code=409,
                            detail="WhatsApp for Mac isn't installed or signed in.") from e
    except store.StoreSchemaError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (PermissionError, sqlite3.OperationalError) as e:
        raise HTTPException(status_code=409, detail=ACCESS_HINT) from e
    except sqlite3.DatabaseError as e:
        if store.is_access_denied(e):
            raise HTTPException(status_code=409, detail=ACCESS_HINT) from e
        raise HTTPException(status_code=409,
                            detail=f"WhatsApp store is unreadable: {e}") from e


def _merged(chats: list[store.Chat]) -> list[dict]:
    allowed = allowlist.load(state_dir())
    return [
        {"jid": c.jid, "name": c.name, "kind": c.kind,
         "lastMessageAt": c.last_message_at.isoformat() if c.last_message_at else None,
         "messageCount": c.message_count, "allowed": c.jid in allowed,
         "context": (allowed.get(c.jid) or {}).get("context")}
        for c in chats
    ]


@router.get("/chats")
def list_whatsapp_chats() -> list[dict]:
    return _merged(_chats())


@router.put("/chats")
def save_whatsapp_chats(body: ChatsBody) -> list[dict]:
    valid = routing_config.contexts()
    for choice in body.chats.values():
        # Unticking must work even when the chat's context was since archived.
        if choice.allowed and choice.context is not None and choice.context not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"unknown context: {choice.context!r}; valid: {sorted(valid)}",
            )
    chats = _chats()
    names = {c.jid: c.name for c in chats}
    current = allowlist.load(state_dir())
    for jid, choice in body.chats.items():
        if jid not in names:
            continue
        if choice.allowed:
            current[jid] = {"name": names[jid], "context": choice.context}
        else:
            current.pop(jid, None)
    allowlist.save(state_dir(), current)
    return _merged(chats)
