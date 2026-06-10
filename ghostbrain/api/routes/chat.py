"""Chat API: conversation CRUD + streaming agentic messages over SSE."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.chat import (
    ChatExportResponse,
    ChatMessageRequest,
    Conversation,
    ConversationSummary,
    RenameRequest,
)
from ghostbrain.api.repo import chat as repo_chat
from ghostbrain.api.repo import chat_export as repo_chat_export
from ghostbrain.api.repo import chat_store
from ghostbrain.llm.client import LLMError

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations() -> list[dict]:
    return chat_store.list_all()


@router.post("", response_model=Conversation)
def create_conversation() -> dict:
    return chat_store.create()


@router.get("/{conv_id}", response_model=Conversation)
def get_conversation(conv_id: str) -> dict:
    conv = chat_store.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.patch("/{conv_id}", response_model=Conversation)
def rename_conversation(conv_id: str, payload: RenameRequest) -> dict:
    conv = chat_store.rename(conv_id, payload.title)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str) -> dict:
    if not chat_store.delete(conv_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


@router.post("/{conv_id}/stop")
def stop_turn(conv_id: str) -> dict:
    return {"stopped": repo_chat.cancel(conv_id)}


@router.post("/{conv_id}/export-jot", response_model=ChatExportResponse)
def export_jot(conv_id: str) -> dict:
    try:
        return repo_chat_export.export_conversation(conv_id)
    except repo_chat_export.ConversationNotFound:
        raise HTTPException(status_code=404, detail="conversation not found")
    except repo_chat_export.NothingToExport:
        raise HTTPException(status_code=400, detail="conversation has no answers to summarize")
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"summary failed: {e}")


@router.post("/{conv_id}/messages")
def send_message(conv_id: str, payload: ChatMessageRequest) -> StreamingResponse:
    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    def gen():
        # Sync generator: starlette runs it in a threadpool and closes it
        # (GeneratorExit) when the client disconnects — that propagates into
        # run_chat_turn's finally, killing the claude subprocess.
        for event in repo_chat.send_message(conv_id, payload.text):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
