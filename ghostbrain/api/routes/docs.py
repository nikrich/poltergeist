"""Docs assistant: streamed writing turns + Confluence export."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.docs import (
    DocsAssistRequest,
    DocsAssistStopRequest,
)
from ghostbrain.api.repo import docs_assist

router = APIRouter(prefix="/v1/docs", tags=["docs"])


@router.post("/assist")
def assist(payload: DocsAssistRequest) -> StreamingResponse:
    def gen():
        # Sync generator: starlette threadpools it and closes it on client
        # disconnect, which kills the claude subprocess (same as chat).
        for event in docs_assist.run_assist(
            payload.jot_id,
            instruction=payload.instruction,
            selection=payload.selection,
            mode=payload.mode,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/assist/stop")
def stop(payload: DocsAssistStopRequest) -> dict:
    return {"stopped": docs_assist.cancel(payload.jot_id)}
