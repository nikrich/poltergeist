"""File a new chat under its context/project after the first reply (spec §2).

Runs once per chat, off the reply stream, using the same router that files
every other inbound item. Unsure or failed -> the chat stays unfiled. A
manual move before the router answers always wins (apply_auto_file checks
the chat is still pending under the store lock).
"""
from __future__ import annotations

import logging
import threading

from ghostbrain.api.repo import chat_store

log = logging.getLogger("ghostbrain.chat.autofile")

EXCERPT_CAP = 4000


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True, name="chat-autofile").start()


def _route(event: dict, *, content_excerpt: str):
    from ghostbrain.worker import router  # lazy: router pulls in the llm stack

    return router.route_event(event, content_excerpt=content_excerpt)


def _reject_below() -> float:
    from ghostbrain.worker import router

    try:
        thresholds = (router._load_yaml("config.yaml") or {}).get("thresholds") or {}
        return float(thresholds.get("reject_below", 0.5))
    except Exception:
        return 0.5


def _full_replies(conv: dict) -> list[dict]:
    return [m for m in conv.get("messages", []) if m["role"] == "assistant" and not m.get("interrupted")]


def maybe_schedule(conv: dict) -> bool:
    """Kick off auto-filing for a pending chat that has a complete assistant reply.

    Stopped (interrupted) replies don't count, so a chat whose first reply was
    stopped is filed after the next full one. A chat whose routing never landed
    (e.g. app restart) is retried on its next finished turn; apply_auto_file's
    under-lock pending check makes a duplicate router call harmless.
    """
    if conv.get("auto_filed") != "pending":
        return False
    if not _full_replies(conv):
        return False
    _spawn(run, conv["id"])
    return True


def _excerpt(conv: dict) -> str:
    user = next((m["text"] for m in conv["messages"] if m["role"] == "user"), "")
    reply = next((m["text"] for m in _full_replies(conv)), "")
    half = EXCERPT_CAP // 2 - 20
    return f"User: {user[:half]}\n\nAssistant: {reply[:half]}"[:EXCERPT_CAP]


def run(conv_id: str) -> None:
    try:
        conv = chat_store.get(conv_id)
        if conv is None or conv["auto_filed"] != "pending":
            return
        context = project = None
        try:
            d = _route(
                {"id": conv_id, "source": "chat", "title": conv["title"]},
                content_excerpt=_excerpt(conv),
            )
            if d.method != "fallback" and d.context != "needs_review" and d.confidence >= _reject_below():
                context, project = d.context, d.project
            log.info("chat %s auto-file -> %s/%s (conf=%.2f, %s)", conv_id, d.context, d.project, d.confidence, d.method)
        except Exception:
            log.warning("auto-filing failed for chat %s", conv_id, exc_info=True)
        chat_store.apply_auto_file(conv_id, context, project)
    except Exception:
        log.exception("auto-file thread failed for chat %s", conv_id)
