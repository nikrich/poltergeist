"""Server-sent events with keepalive comments.

The desktop main process reads assist streams with Node's fetch (undici),
whose dispatcher aborts a response body that stays silent for 300 s. One
agent turn can be silent that long, e.g. a cold semantic-model load plus a
few vault tool calls for a draft. A comment line every KEEPALIVE_S keeps
the body moving; SSE parsers (desktop/src/main/chat-stream.ts
createSseParser) skip lines that don't start with ``data:``.

The event iterator runs on a pump thread so the consumer can time out and
emit keepalives without touching it. A consumer that goes away (client
disconnect → the generator is closed) calls ``on_close``, which must end the
iterator (docs: cancel the agent turn); the pump then closes it.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterable, Iterator

log = logging.getLogger("ghostbrain.api.sse")

KEEPALIVE_S = 15.0
KEEPALIVE = ": keepalive\n\n"
_DONE = object()


def sse_stream(
    events: Iterable[dict],
    *,
    keepalive_s: float | None = None,
    on_close: Callable[[], object] | None = None,
) -> Iterator[str]:
    interval = KEEPALIVE_S if keepalive_s is None else keepalive_s
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def pump() -> None:
        it = iter(events)
        try:
            for event in it:
                q.put(event)
                if stop.is_set():
                    break
        except Exception as e:  # surface as a terminal event
            log.exception("sse: event source failed")
            q.put({"type": "error", "message": f"assist failed: {e}"})
        finally:
            close = getattr(it, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    log.exception("sse: closing the event source failed")
            q.put(_DONE)

    threading.Thread(target=pump, name="sse-pump", daemon=True).start()
    finished = False
    try:
        while True:
            try:
                item = q.get(timeout=interval)
            except queue.Empty:
                yield KEEPALIVE
                continue
            if item is _DONE:
                finished = True
                return
            yield f"data: {json.dumps(item)}\n\n"
    finally:
        if not finished:
            stop.set()
            if on_close is not None:
                try:
                    on_close()
                except Exception:
                    log.exception("sse: on_close failed")
