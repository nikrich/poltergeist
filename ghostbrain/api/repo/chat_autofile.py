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


def maybe_schedule(conv: dict) -> bool:
    """Kick off auto-filing if this conv just got its first reply and is pending."""
    if conv.get("auto_filed") != "pending":
        return False
    if sum(1 for m in conv.get("messages", []) if m["role"] == "assistant") != 1:
        return False
    _spawn(run, conv["id"])
    return True


def _excerpt(conv: dict) -> str:
    user = next((m["text"] for m in conv["messages"] if m["role"] == "user"), "")
    reply = next((m["text"] for m in conv["messages"] if m["role"] == "assistant"), "")
    half = EXCERPT_CAP // 2 - 20
    return f"User: {user[:half]}\n\nAssistant: {reply[:half]}"[:EXCERPT_CAP]


def run(conv_id: str) -> None:
    conv = chat_store.get(conv_id)
    if conv is None or conv["auto_filed"] != "pending":
        return
    context = project = None
    try:
        d = _route({"source": "chat", "title": conv["title"]}, content_excerpt=_excerpt(conv))
        if d.method != "fallback" and d.context != "needs_review" and d.confidence >= _reject_below():
            context, project = d.context, d.project
        log.info("chat %s auto-file -> %s/%s (conf=%.2f, %s)", conv_id, d.context, d.project, d.confidence, d.method)
    except Exception:
        log.warning("auto-filing failed for chat %s", conv_id, exc_info=True)
    chat_store.apply_auto_file(conv_id, context, project)
