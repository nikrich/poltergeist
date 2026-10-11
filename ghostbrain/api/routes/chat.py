"""Chat API: conversation CRUD + streaming agentic messages over SSE."""
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.chat import (
    AttachmentUploadRequest,
    AttachmentUploadResponse,
    ChatExportResponse,
    ChatMessageRequest,
    ChatTree,
    Conversation,
    ConversationSummary,
    UpdateConversationRequest,
)
from ghostbrain.api.repo import chat as repo_chat
from ghostbrain.api.repo import chat_attachments
from ghostbrain.api.repo import chat_export as repo_chat_export
from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo import chat_folders
from ghostbrain.api.models.library import FolderRef, MoveFolderRequest
from ghostbrain.llm.client import LLMError

router = APIRouter(prefix="/v1/chat", tags=["chat"])

MAX_ATTACHMENTS_PER_MESSAGE = 10


@router.get("", response_model=list[ConversationSummary])
def list_conversations() -> list[dict]:
    return chat_store.list_all()


@router.post("", response_model=Conversation)
def create_conversation() -> dict:
    return chat_store.create()


def _folder_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except chat_folders.ChatFolderError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/tree", response_model=ChatTree)
def chat_tree() -> dict:
    return chat_folders.tree()


@router.post("/folders", response_model=FolderRef)
def create_chat_folder(payload: FolderRef) -> dict:
    return _folder_call(chat_folders.create, payload.context, payload.project, payload.path)


@router.patch("/folders", response_model=FolderRef)
def move_chat_folder(payload: MoveFolderRequest) -> dict:
    src, dst = payload.from_, payload.to
    return _folder_call(
        chat_folders.move, (src.context, src.project, src.path), (dst.context, dst.project, dst.path)
    )


@router.delete("/folders")
def delete_chat_folder(context: str, path: str, project: str | None = Query(None)) -> dict:
    _folder_call(chat_folders.delete, context, project, path)
    return {"deleted": True}


@router.get("/{conv_id}", response_model=Conversation)
def get_conversation(conv_id: str) -> dict:
    conv = chat_store.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.patch("/{conv_id}", response_model=Conversation)
def update_conversation(conv_id: str, payload: UpdateConversationRequest) -> dict:
    fields = payload.model_fields_set
    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv = None
    if "context" in fields:
        conv = _folder_call(
            chat_folders.move_chat, conv_id,
            context=payload.context, project=payload.project, folder=payload.folder,
        )
    elif "project" in fields:  # legacy: project = "context/slug" | null
        if payload.project is None:
            conv = _folder_call(chat_folders.move_chat, conv_id, context=None, project=None, folder=None)
        else:
            context, _, slug = payload.project.partition("/")
            if not context or not slug:
                raise HTTPException(status_code=422, detail=f"unknown project: {payload.project}")
            conv = _folder_call(chat_folders.move_chat, conv_id, context=context, project=slug, folder=None)
    elif "folder" in fields:
        raise HTTPException(status_code=422, detail="context is required to move a conversation")
    if "title" in fields:
        conv = chat_store.update(conv_id, title=payload.title)
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
    except repo_chat_export.ExportInProgress:
        raise HTTPException(
            status_code=409,
            detail="an export is already running for this conversation",
        )
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"summary failed: {e}")


@router.post("/{conv_id}/attachments", response_model=AttachmentUploadResponse)
def upload_attachments(conv_id: str, payload: AttachmentUploadRequest) -> dict:
    import base64
    import binascii

    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if len(payload.files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_ATTACHMENTS_PER_MESSAGE} files per message",
        )
    out: list[dict] = []
    for f in payload.files:
        try:
            content = base64.b64decode(f.content_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail=f"invalid base64: {f.name}")
        try:
            out.append(chat_attachments.save_attachment(conv_id, f.name, f.mime, content))
        except chat_attachments.UnsupportedAttachment as e:
            raise HTTPException(status_code=415, detail=str(e))
        except chat_attachments.AttachmentTooLarge as e:
            raise HTTPException(status_code=413, detail=str(e))
    return {"attachments": out}


@router.post("/{conv_id}/messages")
def send_message(conv_id: str, payload: ChatMessageRequest) -> StreamingResponse:
    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    def gen():
        # Sync generator: starlette runs it in a threadpool and closes it
        # (GeneratorExit) when the client disconnects — that propagates into
        # run_chat_turn's finally, killing the claude subprocess.
        for event in repo_chat.send_message(
            conv_id, payload.text, payload.attachment_paths
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
