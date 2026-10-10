"""HTTP glue for the vault write path: If-Match → base_etag, and
vault-write exceptions → status codes, registered once for every route."""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from ghostbrain.history import HistoryUnavailable
from ghostbrain.vault_write import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
    normalize_if_match,
)


def if_match(value: str | None = Header(default=None, alias="If-Match")) -> str | None:
    """FastAPI dependency: the etag a write is based on, or None."""
    return normalize_if_match(value)


def install_vault_write_errors(app: FastAPI) -> None:
    async def _conflict(_req: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, WriteConflict)
        return JSONResponse(
            status_code=409,
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
