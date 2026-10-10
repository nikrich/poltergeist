"""Design-system pack library and design settings.

Packs: list, import (background agent job, polled), delete. Settings: the
``design:`` block of config.yaml (listen for spoken commands, budget per
run, default pack, folders searched for codebases).
"""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ghostbrain.design import packs
from ghostbrain.design import settings as design_settings

router = APIRouter(prefix="/v1/design", tags=["design"])


class DesignPack(BaseModel):
    id: str
    name: str
    source: str
    imported_at: str | None = None
    builtin: bool


class ImportPackRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=2000)
    name: str | None = Field(None, max_length=80)


class DesignPackImportJob(BaseModel):
    id: str
    source: str
    status: str  # running | done | error
    message: str | None = None
    pack_id: str | None = None


class DesignSettings(BaseModel):
    listen: bool
    budget_usd: float
    default_pack: str
    code_roots: list[str]
    web: bool = True


class UpdateDesignSettingsRequest(BaseModel):
    listen: bool | None = None
    budget_usd: float | None = None
    default_pack: str | None = None
    code_roots: list[str] | None = None
    web: bool | None = None


@router.get("/packs", response_model=list[DesignPack])
def list_packs() -> list[dict]:
    return packs.list_packs()


@router.post("/packs/import", response_model=DesignPackImportJob)
def import_pack(payload: ImportPackRequest) -> dict:
    try:
        return packs.start_import(payload.source, payload.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/packs/import/{job_id}", response_model=DesignPackImportJob)
def get_import(job_id: str) -> dict:
    job = packs.get_import(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"import job not found: {job_id}")
    return job


@router.delete("/packs/{pack_id}", status_code=204)
def delete_pack(pack_id: str) -> Response:
    try:
        packs.delete_pack(pack_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"design system not found: {pack_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)


@router.get("/settings", response_model=DesignSettings)
def get_settings() -> dict:
    return design_settings.load()


@router.put("/settings", response_model=DesignSettings)
def put_settings(payload: UpdateDesignSettingsRequest) -> dict:
    try:
        return design_settings.update(**payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
