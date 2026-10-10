"""HTTP glue for the vault write path: If-Match → base_etag, and
vault-write exceptions → status codes, registered once for every route."""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ghostbrain.history import HistoryUnavailable
from ghostbrain.vault_write import (
    RESTORE,
    USER,
    Actor,
    EtagRequired,
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
    normalize_if_match,
    parse_actor,
)


def if_match(value: str | None = Header(default=None, alias="If-Match")) -> str | None:
    """FastAPI dependency: the etag a write is based on, or None."""
    return normalize_if_match(value)


ACTOR_HEADER = "X-Poltergeist-Actor"


def request_actor(value: str | None = Header(default=None, alias=ACTOR_HEADER)) -> Actor:
    """FastAPI dependency (spec B §2): who is writing. A missing header means
    the user. ``worker:*`` and ``restore`` are in-process only."""
    if value is None or not value.strip():
        return USER
    try:
        actor = parse_actor(value.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid {ACTOR_HEADER} header") from None
    if actor == RESTORE or actor.startswith("worker:"):
        raise HTTPException(
            status_code=400, detail=f"{ACTOR_HEADER}: {actor!r} is reserved for in-process writers",
        )
    return actor


def install_vault_write_errors(app: FastAPI) -> None:
    async def _conflict(_req: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, WriteConflict)
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "currentEtag": exc.current_etag},
        )

    async def _etag_required(_req: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, EtagRequired)
        return JSONResponse(
            status_code=428,
            content={"detail": str(exc), "currentEtag": exc.current_etag},
        )

    async def _missing(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"Note not found: {exc}"})

    async def _malformed(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    async def _invalid(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def _history(_req: Request, _exc: Exception) -> JSONResponse:
        # Spec B error handling: a non-user write that cannot be snapshotted
        # is refused; the file is untouched.
        return JSONResponse(status_code=500, content={"detail": "history unavailable"})

    app.add_exception_handler(WriteConflict, _conflict)
    app.add_exception_handler(FileMissing, _missing)
    app.add_exception_handler(MalformedNote, _malformed)
    app.add_exception_handler(InvalidPath, _invalid)
    app.add_exception_handler(HistoryUnavailable, _history)
    app.add_exception_handler(EtagRequired, _etag_required)
