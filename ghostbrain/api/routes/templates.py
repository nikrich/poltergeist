"""Smart templates, slice C1 (spec 2026-10-09-smart-templates-design.md).

GET  /v1/templates                  list (seeds starters if the folder is missing)
GET  /v1/templates/functions        the registry, for intellisense
POST /v1/templates/{id}/create      render + vault_write.write_new(actor=user)
POST /v1/templates/{id}/render      render only (the /template slash insert)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.functions import registry_json
from ghostbrain.templates.registry import TemplateInvalid, TemplateNotFound, list_templates
from ghostbrain.templates.render import AnswerError, RenderError

router = APIRouter(prefix="/v1/templates", tags=["templates"])
_ERRORS = (TemplateNotFound, TemplateInvalid, AnswerError, RenderError)


class AnswersBody(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=50)


def _http_error(template_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, TemplateNotFound):
        return HTTPException(status_code=404, detail=f"template not found: {template_id}")
    if isinstance(exc, TemplateInvalid):
        return HTTPException(status_code=422, detail=f"template has errors: {exc}")
    if isinstance(exc, AnswerError):
        return HTTPException(status_code=422, detail=f"{exc.field}: {exc}")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def get_templates() -> dict[str, Any]:
    return {"templates": [info.to_json() for info in list_templates()]}


@router.get("/functions")
def get_functions() -> dict[str, Any]:
    return registry_json()


@router.post("/{template_id}/create", status_code=201)
def create_note(template_id: str, body: AnswersBody) -> dict[str, Any]:
    # Always the user: the request body has no actor and none is forwarded.
    try:
        created = create_from_template(template_id, body.answers)
    except _ERRORS as e:
        raise _http_error(template_id, e) from e
    return {"path": created.path, "title": created.title, "etag": created.etag, "status": created.status}


@router.post("/{template_id}/render")
def render_note(template_id: str, body: AnswersBody) -> dict[str, Any]:
    try:
        note = preview_from_template(template_id, body.answers)
    except _ERRORS as e:
        raise _http_error(template_id, e) from e
    return {"path": note.path, "folder": note.folder, "filename": note.filename,
            "title": note.title, "frontmatter": note.frontmatter, "body": note.body}
