"""Project registry CRUD. No DELETE — archive only (notes reference projects)."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.project import (
    CreateProjectRequest,
    Project,
    UpdateProjectRequest,
)
from ghostbrain.api.repo import projects as repo

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_projects(includeArchived: bool = Query(False)) -> list[dict]:
    return repo.list_projects(include_archived=includeArchived)


@router.post("", response_model=Project)
def create_project(payload: CreateProjectRequest) -> dict:
    try:
        return repo.create_project(payload.context, payload.name, payload.description)
    except repo.UnknownContext:
        raise HTTPException(
            status_code=422,
            detail=f"unknown context: {payload.context!r}; valid: {sorted(repo.KNOWN_CONTEXTS)}",
        )
    except repo.ProjectExists as e:
        raise HTTPException(status_code=409, detail=f"project already exists: {e}")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/{context}/{slug}", response_model=Project)
def update_project(context: str, slug: str, payload: UpdateProjectRequest) -> dict:
    p = repo.update_project(
        context,
        slug,
        name=payload.name,
        description=payload.description,
        archived=payload.archived,
    )
    if p is None:
        raise HTTPException(status_code=404, detail=f"project not found: {context}/{slug}")
    return p
