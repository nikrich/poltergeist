"""Docs assistant: streamed writing turns + Confluence export."""
import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.docs import (
    ConfluenceExportRequest,
    DocsAssistRequest,
    DocsAssistStopRequest,
    WriteDocRequest,
    WriteDocResponse,
)
from ghostbrain.api.repo import docs_assist, export_confluence, generated_docs
from ghostbrain.api.repo.import_atlassian import ImportNotConfiguredError
from ghostbrain.api.repo.notes_manual import JotNotFound
from ghostbrain.api.sse import sse_stream
from ghostbrain.api.vault_http import request_actor
from ghostbrain.connectors.atlassian._base import AtlassianAuthError
from ghostbrain.vault_write import MCP, USER, Actor

router = APIRouter(prefix="/v1/docs", tags=["docs"])


@router.post("/assist")
def assist(payload: DocsAssistRequest) -> StreamingResponse:
    key = payload.stream_key
    events = docs_assist.run_assist(
        payload.jot_id,
        path=payload.path,
        stream_key=key,
        instruction=payload.instruction,
        selection=payload.selection,
        mode=payload.mode,
        target_language=payload.target_language,
        before=payload.before,
        placement=payload.placement,
    )
    # Keepalive comments stop undici's 300 s body timeout during silent turns.
    # A client disconnect closes the stream → on_close kills the turn (the
    # sync generator is threadpooled by starlette, same as chat).
    return StreamingResponse(
        sse_stream(events, on_close=lambda: docs_assist.cancel(key)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/assist/stop")
def stop(payload: DocsAssistStopRequest) -> dict:
    return {"stopped": docs_assist.cancel(payload.key)}


@router.post("/write", response_model=WriteDocResponse)
def write_doc(payload: WriteDocRequest, actor: Actor = Depends(request_actor)) -> dict:
    # Agent-only tool: a request without the header is still the MCP agent.
    writer = MCP if actor == USER else actor
    try:
        return generated_docs.write_doc(payload.title, payload.html, actor=writer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    # TrackedPageGone / AtlassianAuthError / ImportNotConfiguredError are
    # RuntimeError subclasses — this catch-all must stay LAST so a 429/5xx
    # exhausting retries (RuntimeError) or a network error surfaces as 502,
    # not an opaque 500.
    except (RuntimeError, requests.RequestException) as e:
        raise HTTPException(status_code=502, detail=f"confluence request failed: {e}")
