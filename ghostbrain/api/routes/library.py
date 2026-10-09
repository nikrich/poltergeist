"""Docs library API (spec §3). Library errors carry their own HTTP status."""
import base64
import binascii

from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.library import (
    AdoptRequest,
    DocDetail,
    DocSummary,
    FolderRef,
    LibraryTree,
    MoveFolderRequest,
    PatchDocRequest,
    RemoveOrphanRequest,
    UploadDocRequest,
    UploadDocResponse,
)
from ghostbrain.api.repo.doc_library import folders, index, ops, search
from ghostbrain.api.repo.doc_library.errors import LibraryError

router = APIRouter(prefix="/v1/library", tags=["library"])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LibraryError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


@router.get("/tree", response_model=LibraryTree)
def get_tree(context: str | None = None, project: str | None = None) -> dict:
    return _run(index.tree, context, project)


@router.post("/docs", response_model=UploadDocResponse)
def upload_doc(payload: UploadDocRequest) -> dict:
    try:
        content = base64.b64decode(payload.content_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid base64: {payload.name}") from e
    return _run(
        ops.upload, payload.context, payload.project, payload.folder,
        payload.name, payload.mime, content,
    )


@router.get("/docs/{doc_id}", response_model=DocDetail)
def get_doc(doc_id: str) -> dict:
    return _run(lambda: index.detail(index.get(doc_id)))


@router.patch("/docs/{doc_id}", response_model=DocSummary)
def patch_doc(doc_id: str, payload: PatchDocRequest) -> dict:
    if payload.title is None and payload.context is None:
        raise HTTPException(status_code=422, detail="nothing to change: pass title and/or context")
    result: dict = {}
    if payload.title is not None:
        result = _run(ops.rename, doc_id, payload.title)
    if payload.context is not None:
        result = _run(ops.move, doc_id, payload.context, payload.project, payload.folder)
    return result


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: str) -> dict:
    _run(ops.delete, doc_id)
    return {"deleted": True}


@router.post("/docs/{doc_id}/reindex", response_model=DocSummary)
def reindex_doc(doc_id: str) -> dict:
    return _run(ops.reindex, doc_id)


@router.post("/folders", response_model=FolderRef)
def create_folder(payload: FolderRef) -> dict:
    return _run(folders.create, payload.context, payload.project, payload.path)


@router.patch("/folders", response_model=FolderRef)
def move_folder(payload: MoveFolderRequest) -> dict:
    src, dst = payload.from_, payload.to
    return _run(
        folders.move, (src.context, src.project, src.path), (dst.context, dst.project, dst.path)
    )


@router.delete("/folders")
def delete_folder(context: str, path: str, project: str | None = Query(None)) -> dict:
    _run(folders.delete, context, project, path)
    return {"deleted": True}


@router.post("/attention/adopt", response_model=DocSummary)
def adopt(payload: AdoptRequest) -> dict:
    return _run(ops.adopt, payload.context, payload.project, payload.folder, payload.name)


@router.post("/attention/remove-orphan")
def remove_orphan(payload: RemoveOrphanRequest) -> dict:
    _run(ops.remove_orphan, payload.doc_id)
    return {"removed": True}


@router.get("/search", response_model=list[DocSummary])
def search_docs(q: str = "", project: str | None = None) -> list[dict]:
    return search.search(q, project)
