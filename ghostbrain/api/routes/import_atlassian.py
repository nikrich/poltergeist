"""/v1/import — browse Confluence/Jira and bulk-import items into the vault."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.import_atlassian import (
    ConfluencePagesResponse,
    ImportJiraIssue,
    ImportPage,
    ImportRequest,
    ImportResponse,
    ImportSpace,
)
from ghostbrain.api.repo import import_atlassian as repo
from ghostbrain.api.repo.import_atlassian import ImportNotConfiguredError

router = APIRouter(prefix="/v1/import", tags=["import"])


@router.get("/confluence/spaces", response_model=list[ImportSpace])
def confluence_spaces() -> list[dict]:
    try:
        return repo.list_spaces()
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/confluence/pages", response_model=ConfluencePagesResponse)
def confluence_pages(
    site: str = Query(...),
    space: str = Query(...),
    parent: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None),
) -> dict:
    try:
        return repo.list_confluence_pages(
            site=site, space=space, parent=parent, limit=limit, cursor=cursor
        )
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        # Invalid query input (bad parent id, unknown site, unmonitored
        # space) → 400, matching notes.py's invalid-path convention.
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/confluence/search", response_model=list[ImportPage])
def confluence_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=100),
) -> list[dict]:
    try:
        return repo.search_confluence(q=q, limit=limit)
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/jira/issues", response_model=list[ImportJiraIssue])
def jira_issues(
    q: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
) -> list[dict]:
    try:
        return repo.list_jira_issues(q=q, limit=limit)
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("", response_model=ImportResponse)
def bulk_import(payload: ImportRequest) -> dict:
    # >50 / empty / missing id|key → 422 from the pydantic model before we
    # ever get here. Unconfigured connector → 409 from the upfront check.
    try:
        results = repo.import_items([i.model_dump() for i in payload.items])
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"results": results}
