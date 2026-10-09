"""GET /v1/connectors, GET /v1/connectors/{id}, POST sync endpoints, PATCH accounts."""
from __future__ import annotations

import dataclasses
from dataclasses import asdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from httplib2 import HttpLib2Error
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ghostbrain import accounts
from ghostbrain.api.models.connector import Connector, ConnectorDetail
from ghostbrain.api.repo.connectors import get_connector, list_connectors
from ghostbrain.connectors.gdrive import backfill as gdrive_backfill
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.drive import DriveApiDisabled, DriveRateLimited
from ghostbrain.connectors.gmail import backfill as gmail_backfill
from ghostbrain.connectors.gmail.auth import GmailAuthError

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


# Mirror of the scheduler's job registry. Kept here so the sync endpoints can
# 404 unknown connector ids without touching the (maybe-not-running) scheduler.
SYNCABLE = {
    "github", "gmail", "slack", "calendar", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings", "gdrive", "whatsapp",
}


@router.get("", response_model=list[Connector])
def connectors() -> list[dict]:
    return list_connectors()


@router.get("/{connector_id}", response_model=ConnectorDetail)
def connector_detail(connector_id: str) -> dict:
    record = get_connector(connector_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Connector not found: {connector_id}")
    return record


@router.post("/{connector_id}/sync")
async def sync_one(connector_id: str, request: Request) -> dict:
    if connector_id not in SYNCABLE:
        raise HTTPException(status_code=404, detail=f"Connector not syncable: {connector_id}")
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Scheduler not running. Enable 'Run scheduler in-app' in Settings.",
        )
    result = await sched.run_now(connector_id)
    return asdict(result)


@router.post("/sync-all")
async def sync_all(request: Request) -> dict:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Scheduler not running. Enable 'Run scheduler in-app' in Settings.",
        )
    results = await sched.run_all()
    return {name: asdict(r) for name, r in results.items()}


def _since_for_years(years: int) -> date:
    today = datetime.now(UTC).astimezone().date()  # local calendar day
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29 -> Feb 28
        return today.replace(year=today.year - years, day=28)


def _gmail_account_or_404(account_id: str) -> None:
    if accounts.get_account("gmail", account_id) is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")


class BackfillStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    years: int = Field(ge=1, le=10)


@router.get("/gmail/accounts/{account_id}/backfill")
def get_backfill(account_id: str) -> dict:
    _gmail_account_or_404(account_id)
    state = gmail_backfill.get(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.get("/gmail/accounts/{account_id}/backfill/estimate")
def backfill_estimate(account_id: str, years: int = Query(..., ge=1, le=10)) -> dict:
    _gmail_account_or_404(account_id)
    since = _since_for_years(years)
    try:
        threads = gmail_backfill.estimate(account_id, since=since)
    except GmailAuthError as e:
        raise HTTPException(status_code=409, detail=gmail_backfill.AUTH_ERROR_MESSAGE) from e
    return {"threads": threads, "since": since.isoformat()}


@router.post("/gmail/accounts/{account_id}/backfill", status_code=201)
def start_backfill(account_id: str, body: BackfillStartBody, request: Request) -> dict:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Backfill needs the in-app scheduler. Enable 'Run scheduler in-app' in Settings.",
        )
    _gmail_account_or_404(account_id)
    gmail_backfill.start(account_id, since=_since_for_years(body.years))
    return gmail_backfill.get(account_id)


@router.post("/gmail/accounts/{account_id}/backfill/pause")
def pause_backfill(account_id: str) -> dict:
    _gmail_account_or_404(account_id)
    state = gmail_backfill.pause(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.post("/gmail/accounts/{account_id}/backfill/resume")
def resume_backfill(account_id: str) -> dict:
    _gmail_account_or_404(account_id)
    state = gmail_backfill.resume(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.delete("/gmail/accounts/{account_id}/backfill")
def delete_backfill(account_id: str) -> dict:
    _gmail_account_or_404(account_id)
    gmail_backfill.cancel(account_id)
    return {"ok": True}


GDRIVE_BUSY_MESSAGE = "Google Drive is busy — try the estimate again in a minute"


def _gdrive_account_or_404(account_id: str) -> None:
    if accounts.get_account("gdrive", account_id) is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")


@router.get("/gdrive/accounts/{account_id}/backfill")
def get_gdrive_backfill(account_id: str) -> dict:
    _gdrive_account_or_404(account_id)
    state = gdrive_backfill.get(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.get("/gdrive/accounts/{account_id}/backfill/estimate")
def gdrive_backfill_estimate(account_id: str, years: int = Query(..., ge=1, le=10)) -> dict:
    _gdrive_account_or_404(account_id)
    since = _since_for_years(years)
    try:
        result = gdrive_backfill.estimate(account_id, since=since)
    except GdriveAuthError as e:
        raise HTTPException(status_code=409, detail=gdrive_backfill.AUTH_ERROR_MESSAGE) from e
    except DriveApiDisabled as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (DriveRateLimited, OSError, TimeoutError, HttpLib2Error) as e:
        raise HTTPException(status_code=503, detail=GDRIVE_BUSY_MESSAGE) from e
    return {**result, "since": since.isoformat()}


@router.post("/gdrive/accounts/{account_id}/backfill", status_code=201)
def start_gdrive_backfill(account_id: str, body: BackfillStartBody, request: Request) -> dict:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Backfill needs the in-app scheduler. Enable 'Run scheduler in-app' in Settings.",
        )
    _gdrive_account_or_404(account_id)
    gdrive_backfill.start(account_id, since=_since_for_years(body.years))
    return gdrive_backfill.get(account_id)


@router.post("/gdrive/accounts/{account_id}/backfill/pause")
def pause_gdrive_backfill(account_id: str) -> dict:
    _gdrive_account_or_404(account_id)
    state = gdrive_backfill.pause(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.post("/gdrive/accounts/{account_id}/backfill/resume")
def resume_gdrive_backfill(account_id: str) -> dict:
    _gdrive_account_or_404(account_id)
    state = gdrive_backfill.resume(account_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return state


@router.delete("/gdrive/accounts/{account_id}/backfill")
def delete_gdrive_backfill(account_id: str) -> dict:
    _gdrive_account_or_404(account_id)
    gdrive_backfill.cancel(account_id)
    return {"ok": True}


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: str | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _enabled_not_null(self) -> AccountPatch:
        # `context: null` unassigns the context, but `enabled` is a bool
        # flag with no "unset" meaning — omit it to leave it unchanged,
        # never send it explicitly as null.
        if "enabled" in self.model_fields_set and self.enabled is None:
            raise ValueError("enabled must not be null; omit it to leave it unchanged")
        return self


@router.patch("/{connector_id}/accounts/{account_id}")
def update_account(connector_id: str, account_id: str, body: AccountPatch) -> dict:
    from ghostbrain import accounts, accounts_health

    acct_connector = accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(connector_id)
    if acct_connector is None:
        raise HTTPException(status_code=404, detail=f"Connector has no accounts: {connector_id}")
    acc = accounts.get_account(acct_connector, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    changes = body.model_dump(exclude_unset=True)
    updated = dataclasses.replace(acc, **changes)
    try:
        # Only validate the context when the request sets one: toggling
        # `enabled` must still work on an account whose context was archived.
        accounts.upsert_account(updated, check_context="context" in changes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    persisted = accounts.get_account(acct_connector, updated.id)
    return {
        "id": persisted.id,
        "context": persisted.context,
        "enabled": persisted.enabled,
        "health": accounts_health.health_for(connector_id, persisted.id),
    }
