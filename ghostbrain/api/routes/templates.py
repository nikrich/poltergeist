"""Smart templates, slice C1 (spec 2026-10-09-smart-templates-design.md).

GET  /v1/templates                  list (seeds starters if the folder is missing)
GET  /v1/templates/functions        the registry, for intellisense
POST /v1/templates/{id}/create      render + vault_write.write_new(actor=user)
POST /v1/templates/{id}/render      render only (the /template slash insert)

Slice C3 (template editor):
POST  /v1/templates/lint            diagnostics for template source
POST  /v1/templates/render          Test run: render source with sample answers, write nothing
GET   /v1/templates/query-values    known note types and statuses for query completions
GET   /v1/templates/{id}/source     the file's text and etag
PATCH /v1/templates/{id}/source     save (If-Match), through the write path
POST  /v1/templates                 new blank template

Slice C4 (AI-generated templates):
POST /v1/templates/generate         draft with the AI, validate, save as a pending change
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ghostbrain.api.repo.settings import ProviderUnavailable, require_provider
from ghostbrain.api.vault_http import if_match, request_actor
from ghostbrain.changes.log import ChangeLogError
from ghostbrain.history import HistoryUnavailable
from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.functions import registry_json
from ghostbrain.templates.generate import (
    MAX_DESCRIPTION_CHARS,
    DraftInvalid,
    GenerateError,
    ProviderCannotDraft,
    clean_description,
    draft_template,
    drafting_provider,
)
from ghostbrain.templates.lang import MAX_TEMPLATE_CHARS
from ghostbrain.templates.lint import lint
from ghostbrain.templates.registry import TemplateInvalid, TemplateNotFound, list_templates
from ghostbrain.templates.render import AnswerError, RenderError
from ghostbrain.templates.source import (
    MAX_NAME_CHARS,
    SourceTooLarge,
    create_blank,
    query_values,
    read_source,
    save_source,
)
from ghostbrain.templates.testrun import dry_run
from ghostbrain.vault_write import USER, Actor, InvalidPath, NotHeldError, WriteConflict

log = logging.getLogger("ghostbrain.api.templates")
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


# ── C3: template editor ───────────────────────────────────────────────────


class SourceBody(BaseModel):
    source: str = Field(max_length=MAX_TEMPLATE_CHARS)


class DryRunBody(BaseModel):
    source: str = Field(max_length=MAX_TEMPLATE_CHARS)
    answers: dict[str, str] = Field(default_factory=dict, max_length=50)
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    dry_run: Literal[True] = True


class NewTemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)


@router.post("/lint")
def lint_source(body: SourceBody) -> dict[str, Any]:
    return {"diagnostics": [d.to_json() for d in lint(body.source)]}


@router.post("/render")
def dry_run_source(body: DryRunBody) -> dict[str, Any]:
    """Test run. Always 200: problems come back in ``error``/``diagnostics``
    so the editor can show them next to the source."""
    return dry_run(body.source, body.answers, template_id=body.id or "draft").to_json()


@router.get("/query-values")
def get_query_values() -> dict[str, Any]:
    return query_values()


@router.get("/{template_id}/source")
def get_source(template_id: str) -> dict[str, Any]:
    try:
        return read_source(template_id).to_json()
    except (TemplateNotFound, TemplateInvalid) as e:
        raise _http_error(template_id, e) from e


@router.patch("/{template_id}/source")
def patch_source(
    template_id: str,
    body: SourceBody,
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> dict[str, Any]:
    try:
        saved = save_source(template_id, body.source, actor=actor, base_etag=base_etag)
    except (TemplateNotFound, TemplateInvalid) as e:
        raise _http_error(template_id, e) from e
    except SourceTooLarge as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return saved.to_json()


@router.post("", status_code=201)
def new_template(body: NewTemplateBody, actor: Actor = Depends(request_actor)) -> dict[str, Any]:
    try:
        return create_blank(body.name, actor=actor).to_json()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ── C4: AI-generated templates ────────────────────────────────────────────


class GenerateBody(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)


@router.post("/generate")
def generate_template(body: GenerateBody, actor: Actor = Depends(request_actor)) -> dict[str, Any]:
    """Draft a template with the AI. 200 with ``status: "pending"`` (saved as
    an assistant change that waits for approval) or ``status: "invalid"``
    (failed validation twice; the draft comes back, nothing is saved).

    User-only: the change is recorded as the assistant's, so only the user
    may ask for it (a plugin proposes as itself through the write path).
    Nothing here approves the change."""
    from ghostbrain.templates.ai_save import NotHeld, save_ai_template

    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can ask the assistant to draft a template")
    description = clean_description(body.description)
    if not description:
        raise HTTPException(status_code=422, detail="describe the template you want")
    try:
        require_provider()
    except ProviderUnavailable as e:
        raise HTTPException(status_code=412, detail=str(e)) from e
    try:
        drafting_provider()  # refuse before any turn on a provider that cannot limit its tools
        draft = draft_template(description)
    except ProviderCannotDraft as e:
        raise HTTPException(status_code=412, detail=str(e)) from e
    except GenerateError as e:
        raise HTTPException(status_code=502, detail=f"template generation failed — {e}") from e
    except DraftInvalid as e:
        return {"status": "invalid", "message": str(e), "draft": e.draft,
                "diagnostics": [d.to_json() for d in e.problems]}
    try:
        saved = save_ai_template(draft.source, draft.template,
                                 reason=f"AI template: {' '.join(description.split())[:120]}")
    except DraftInvalid as e:  # unreachable: the draft was just checked
        raise HTTPException(status_code=500, detail=f"the AI template was not saved: {e}") from e
    except NotHeld as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except NotHeldError as e:  # unreachable defence in depth: ai_save turns it into NotHeld
        raise HTTPException(status_code=500, detail="the AI template was not held for approval; "
                                                    "nothing was saved") from e
    except WriteConflict as e:
        raise HTTPException(status_code=409, detail="no free template name — rename or delete "
                                                    "an old template") from e
    except InvalidPath as e:
        log.warning("AI template not saved: %s", e)
        raise HTTPException(status_code=409, detail="the templates folder cannot be written "
                                                    "(is it outside the vault?)") from e
    except HistoryUnavailable as e:
        raise HTTPException(status_code=503, detail="history is unavailable, so the AI template "
                                                    "was not saved; try again") from e
    except ChangeLogError as e:
        raise HTTPException(status_code=503, detail="the change log is unavailable, so the AI "
                                                    "template was not saved; try again") from e
    return saved.to_json()
