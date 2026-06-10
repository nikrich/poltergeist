"""Docs assistant: streamed writing turns + Confluence export."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.docs import (
    ConfluenceExportRequest,
    DocsAssistRequest,
    DocsAssistStopRequest,
)
from ghostbrain.api.repo import docs_assist, export_confluence
from ghostbrain.api.repo.import_atlassian import ImportNotConfiguredError
from ghostbrain.api.repo.notes_manual import JotNotFound
from ghostbrain.connectors.atlassian._base import AtlassianAuthError

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


@router.post("/export/confluence")
def export_to_confluence(payload: ConfluenceExportRequest) -> dict:
    try:
        return export_confluence.export_jot(
            payload.jot_id,
            space_key=payload.space_key,
            parent_id=payload.parent_id,
            title=payload.title,
            force_new=payload.force_new,
        )
    except JotNotFound:
        raise HTTPException(status_code=404, detail="jot not found")
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except export_confluence.TrackedPageGone:
        raise HTTPException(
            status_code=409,
            detail="the Confluence page this jot was exported to no longer exists",
        )
    except AtlassianAuthError as e:
        raise HTTPException(status_code=502, detail=str(e))
