"""Google Drive backfill job: month cursor, paging, resume, guards, round-robin.
Mirrors tests/test_gmail_backfill.py, adapted to Drive's modifiedTime windows."""
from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from ghostbrain.connectors.gdrive import backfill, drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.paths import state_dir, vault_path
from tests.gdrive_fakes import FakeDrive, drive_file, fake_services, http_error

TODAY = date(2026, 9, 28)
ACC = "a@x.com"
ACC2 = "b@x.com"
STATE = "gdrive_backfill.a_at_x_com.json"


# ------------------------------------------------------------------ fixtures

def write_accounts(entries: list[dict]) -> None:
    (vault_path() / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8"
    )


DRIVES: dict[str, object] = {}


@pytest.fixture(autouse=True)
def v(monkeypatch) -> Path:
    root = vault_path()
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, agencyx]\n", encoding="utf-8",
    )
    write_accounts([{"connector": "gdrive", "id": ACC}, {"connector": "gdrive", "id": ACC2}])
    monkeypatch.setattr(backfill, "_today", lambda: TODAY)
    clock = itertools.count()
    base = datetime(2026, 9, 28, 12, tzinfo=UTC)
    monkeypatch.setattr(backfill, "_now", lambda: base + timedelta(seconds=next(clock)))
    monkeypatch.setattr(drive, "_sleep", lambda s: None)
    DRIVES.clear()

    def services_for(acc):
        d = DRIVES.get(acc)
        if isinstance(d, BaseException):
            raise d
        return fake_services(drive=d if d is not None else FakeDrive())

    monkeypatch.setattr(backfill, "_services_for", services_for)
    return root


class Recorder:
    """Stand-in for ingest.ingest_file: records ids, returns scripted outcomes."""

    def __init__(self, outcomes: dict[str, str] | None = None,
                 fallbacks: bool | list[bool] = False, hook=None):
        self.ids: list[str] = []
        self.accounts: list[str] = []
        self.outcomes = outcomes or {}
        self.fallbacks = fallbacks
        self.hook = hook

    def __call__(self, services, account, file, folders):
        assert isinstance(folders, dict)
        self.ids.append(file["id"])
        self.accounts.append(account)
        outcome = self.outcomes.get(file["id"], "imported")
        if isinstance(self.fallbacks, bool):
            fb = self.fallbacks
        else:
            fb = self.fallbacks.pop(0)
        if self.hook is not None:
            self.hook(self, file)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, (fb and outcome == "imported")


@pytest.fixture
def rec(monkeypatch) -> Recorder:
    r = Recorder()
    monkeypatch.setattr(ingest, "ingest_file", r)
    return r


def month_files(*keys_counts, **kw) -> list[dict]:
    """``n`` files per "YYYY-MM", modified on the 15th, newest first."""
    out = []
    for key, n in keys_counts:
        for i in range(n):
            out.append(drive_file(f"{key}-{i:02d}", modified=f"{key}-15T10:{i:02d}:00.000Z", **kw))
    return out


def fake(files: list[dict], acc: str = ACC) -> FakeDrive:
    d = FakeDrive(files)
    DRIVES[acc] = d
    return d


def tick(**kw):
    return backfill.run_tick(**kw)


def window(call: dict) -> str:
    return call["q"].split(") and ", 1)[1]


# --------------------------------------------------------------------- start

def test_start_creates_running_state_and_is_idempotent():
    assert backfill.BATCH_SIZE == 25 and backfill.MAX_YEARS == 10
    assert backfill.LIST_PAGE_SIZE == 100
    assert backfill.ESTIMATE_CAP == 5000 and backfill.ROUTING_FALLBACK_LIMIT == 5
    st = backfill.start(ACC, since=date(2025, 9, 28))
    assert st["status"] == "running" and st["account"] == ACC
    assert st["since"] == "2025-09-28" and st["cursor"] == "2026-09"
    assert st["pageToken"] is None and st["pageDone"] == []
    for key in ("imported", "updated", "skipped", "failed", "tooLarge", "routingFallbacks"):
        assert st[key] == 0
    assert st["error"] is None and st["startedAt"] and st["updatedAt"]
    assert (state_dir() / STATE).exists()
    assert backfill.state_path(ACC) == state_dir() / STATE

    assert backfill.start(ACC, since=date(2020, 1, 1)) == st
    with pytest.raises(KeyError):
        backfill.start("nobody@x.com", since=date(2025, 1, 1))


def test_start_unknown_connector_account_raises(v):
    write_accounts([{"connector": "gmail", "id": ACC}])
    with pytest.raises(KeyError):
        backfill.start(ACC, since=date(2026, 1, 1))


def test_start_after_done_restarts(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake([])
    tick()
    assert backfill.get(ACC)["status"] == "done"
    st = backfill.start(ACC, since=date(2026, 8, 1))
    assert st["status"] == "running" and st["since"] == "2026-08-01"


def test_since_clamped_to_ten_years():
    assert backfill.start(ACC, since=date(1999, 1, 1))["since"] == "2016-09-28"


# ------------------------------------------------------------ month walking

def test_tick_ingests_batch_and_persists_counts(rec):
    backfill.start(ACC, since=date(2026, 1, 1))
    d = fake(month_files(("2026-09", 30)))
    out = tick()
    assert out == {"account": ACC, "status": "running", "imported": 25, "updated": 0,
                   "skipped": 0, "failed": 0, "tooLarge": 0, "cursor": "2026-09"}
    assert len(rec.ids) == 25 and set(rec.accounts) == {ACC}
    call = d.list_calls[0]
    assert window(call) == ("modifiedTime > '2026-08-31T23:59:59' "
                            "and modifiedTime < '2026-10-01T00:00:00'")
    assert call["pageSize"] == 100 and call["pageToken"] is None
    st = backfill.get(ACC)
    # 25 processed caps the tick mid-page; the page is continued next tick
    assert st["imported"] == 25 and st["pageToken"] is None and len(st["pageDone"]) == 25


def test_months_walk_back_with_paging_until_done(rec):
    backfill.start(ACC, since=date(2026, 7, 10))
    d = fake(month_files(("2026-09", 30), ("2026-08", 3), ("2026-07", 2), ("2026-06", 4)))
    out = tick()
    assert out["cursor"] == "2026-09"
    out = tick()
    assert d.list_calls[1]["pageToken"] is None  # same page, continued
    assert out["imported"] == 5 and out["cursor"] == "2026-08"
    assert backfill.get(ACC)["pageToken"] is None
    out = tick()
    assert out["imported"] == 3 and out["cursor"] == "2026-07"
    out = tick()
    # the since day bounds the last window: after = since 00:00 UTC - 1 s
    assert window(d.list_calls[3]) == ("modifiedTime > '2026-07-09T23:59:59' "
                                       "and modifiedTime < '2026-08-01T00:00:00'")
    assert out["imported"] == 2 and out["status"] == "done"
    assert tick() == {"skipped": "idle"}
    st = backfill.get(ACC)
    assert st["imported"] == 35 and st["monthsDone"] == st["monthsTotal"] == 3
    assert not any(i.startswith("2026-06") for i in rec.ids)


def test_empty_month_steps_back(rec):
    backfill.start(ACC, since=date(2026, 1, 1))
    fake([])
    out = tick()
    assert out["cursor"] == "2026-08" and out["status"] == "running" and out["imported"] == 0


def test_december_to_january_boundaries(rec, monkeypatch):
    monkeypatch.setattr(backfill, "_today", lambda: date(2027, 1, 10))
    backfill.start(ACC, since=date(2026, 1, 1))
    d = fake([])
    tick()
    assert window(d.list_calls[0]).endswith("< '2027-02-01T00:00:00'")
    assert backfill.get(ACC)["cursor"] == "2026-12"
    tick()
    assert window(d.list_calls[1]) == ("modifiedTime > '2026-11-30T23:59:59' "
                                       "and modifiedTime < '2027-01-01T00:00:00'")


def test_month_boundary_file_is_included(rec):
    backfill.start(ACC, since=date(2026, 7, 1))
    fake([drive_file("edge", modified="2026-08-01T00:00:00.000Z"),
          drive_file("jul", modified="2026-07-01T00:00:00.000Z"),
          drive_file("sep", modified="2026-09-01T00:00:00.000Z")])
    while tick() != {"skipped": "idle"}:
        pass
    assert sorted(rec.ids) == ["edge", "jul", "sep"]
    assert rec.ids.count("edge") == 1
    assert backfill.get(ACC)["status"] == "done"


def test_outcomes_are_counted(rec):
    rec.outcomes = {"2026-09-00": "tooLarge", "2026-09-01": "updated",
                    "2026-09-02": "skipped", "2026-09-03": "failed"}
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 5)))
    out = tick()
    assert (out["imported"], out["updated"], out["skipped"], out["failed"], out["tooLarge"]) \
        == (1, 1, 1, 1, 1)
    st = backfill.get(ACC)
    assert (st["imported"], st["updated"], st["skipped"], st["failed"], st["tooLarge"]) \
        == (1, 1, 1, 1, 1)


def test_files_not_mine_are_ignored(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 2))
         + [drive_file("theirs", modified="2026-09-20T00:00:00.000Z",
                       owned=False, modified_by_me=False)])
    out = tick()
    assert sorted(rec.ids) == ["2026-09-00", "2026-09-01"] and out["imported"] == 2


def test_resume_after_crash_skips_page_done(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 30)))
    # newest first: page "25" holds 04..00
    backfill._update(ACC, pageToken="25", pageDone=["2026-09-03", "2026-09-01"])
    out = tick()
    assert rec.ids == ["2026-09-04", "2026-09-02", "2026-09-00"]
    assert out["imported"] == 3 and out["cursor"] == "2026-08"
    assert backfill.get(ACC)["pageDone"] == []


# ------------------------------------------------------------------ errors

def test_auth_error_needs_reauth_then_resume(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 2)))
    d.fail_next = [http_error(401, "authError")]
    out = tick()
    assert out["status"] == "error"
    st = backfill.get(ACC)
    assert st["error"] == backfill.AUTH_ERROR_MESSAGE == "needs re-auth"
    assert st["cursor"] == "2026-09"
    assert tick() == {"skipped": "idle"}

    st = backfill.resume(ACC)
    assert st["status"] == "running" and st["error"] is None and st["routingFallbacks"] == 0
    assert tick()["imported"] == 2


def test_no_token_or_refresh_error_needs_reauth(rec):
    from google.auth.exceptions import RefreshError

    backfill.start(ACC, since=date(2026, 9, 1))
    DRIVES[ACC] = GdriveAuthError("no token")
    assert tick()["status"] == "error"
    assert backfill.get(ACC)["error"] == "needs re-auth"

    backfill.cancel(ACC)
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 1)))
    d.fail_next = [RefreshError("invalid_grant")]
    assert tick()["status"] == "error"
    assert backfill.get(ACC)["error"] == "needs re-auth"


def test_auth_error_from_ingest_stops_tick(rec):
    rec.outcomes = {"2026-09-01": GdriveAuthError("revoked")}
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 3)))
    out = tick()
    assert out["status"] == "error" and out["imported"] == 1 and out["failed"] == 0
    st = backfill.get(ACC)
    assert st["error"] == "needs re-auth" and st["imported"] == 1


def test_api_disabled_stores_enable_message(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 1)))
    d.fail_next = [http_error(403, "accessNotConfigured")]
    assert tick()["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error"
    assert st["error"] == ("Enable the Google Drive API in Google Cloud for your OAuth "
                           "client's project (APIs & Services → Library).")


def test_rate_limited_is_transient_and_keeps_page(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 30)))
    tick()
    before = backfill.get(ACC)
    d.fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    out = tick()
    assert out["status"] == "running"
    st = backfill.get(ACC)
    assert st["status"] == "running" and st["error"] == "DriveRateLimited"
    assert (st["cursor"], st["pageToken"], st["pageDone"]) == \
        (before["cursor"], before["pageToken"], before["pageDone"])
    assert st["updatedAt"] > before["updatedAt"]
    out = tick()
    assert out["imported"] == 5 and backfill.get(ACC)["error"] is None


def test_rate_limit_from_ingest_keeps_page_done(rec):
    rec.outcomes = {"2026-09-01": drive.DriveRateLimited("slow down")}
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 4)))
    out = tick()
    assert out["status"] == "running" and out["imported"] == 2
    st = backfill.get(ACC)
    assert st["error"] == "DriveRateLimited" and st["cursor"] == "2026-09"
    assert st["pageDone"] == ["2026-09-03", "2026-09-02"]
    rec.outcomes = {}
    out = tick()
    assert out["imported"] == 2 and out["cursor"] == "2026-08"
    assert rec.ids == ["2026-09-03", "2026-09-02", "2026-09-01", "2026-09-01", "2026-09-00"]


@pytest.mark.parametrize("exc", [http_error(503, "backendError"), TimeoutError("t"), OSError("x")])
def test_other_transient_errors_keep_running(rec, monkeypatch, exc):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 30)))
    tick()
    before = backfill.get(ACC)

    def boom(*a, **kw):
        raise exc

    monkeypatch.setattr(drive, "list_page", boom)
    assert tick()["status"] == "running"
    st = backfill.get(ACC)
    assert st["error"] == type(exc).__name__
    assert (st["cursor"], st["pageToken"]) == (before["cursor"], before["pageToken"])


def test_transient_error_moves_round_robin_on(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    backfill.start(ACC2, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 2)))
    fake([], ACC2)
    d.fail_next = [http_error(503, "backendError")] * (drive.MAX_RETRIES + 1)
    assert tick()["account"] == ACC
    assert tick()["account"] == ACC2
    out = tick()
    assert out["account"] == ACC and out["imported"] == 2


def test_400_with_page_token_clears_token_and_redoes_month(rec, monkeypatch):
    monkeypatch.setattr(backfill, "LIST_PAGE_SIZE", 25)
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 30)))
    tick()
    backfill._update(ACC, pageDone=["2026-09-25"])
    d.fail_next = [http_error(400, "invalid")]
    out = tick()
    assert out["status"] == "running"
    st = backfill.get(ACC)
    assert st["pageToken"] is None and st["pageDone"] == [] and st["cursor"] == "2026-09"
    assert st["error"] == "HttpError"
    tick()
    assert d.list_calls[-1]["pageToken"] is None


@pytest.mark.parametrize("exc", [OSError("wifi dropped"), TimeoutError("t")])
def test_network_error_from_ingest_is_transient_and_keeps_file(rec, exc):
    rec.outcomes = {"2026-09-01": exc}  # the 2nd file (newest first: 02, 01, 00)
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 3)))
    out = tick()
    assert out["status"] == "running" and out["imported"] == 1 and out["failed"] == 0
    st = backfill.get(ACC)
    assert st["status"] == "running" and st["error"] == type(exc).__name__
    assert st["pageDone"] == ["2026-09-02"]
    assert st["cursor"] == "2026-09" and st["pageToken"] is None and st["failed"] == 0
    rec.outcomes = {}
    out = tick()
    assert out["imported"] == 2 and out["cursor"] == "2026-08"
    assert rec.ids == ["2026-09-02", "2026-09-01", "2026-09-01", "2026-09-00"]
    assert backfill.get(ACC)["error"] is None


@pytest.mark.parametrize("reason", ["insufficientPermissions", "forbidden"])
def test_403_permission_on_list_needs_reauth(rec, reason, monkeypatch):
    monkeypatch.setattr(backfill, "LIST_PAGE_SIZE", 25)
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 30)))
    tick()  # a page token is set: 403 must still mean re-auth, not a token reset
    d.fail_next = [http_error(403, reason)]
    assert tick()["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error" and st["error"] == "needs re-auth"
    assert st["pageToken"] == "25"


@pytest.mark.parametrize("status", [400, 404])
def test_4xx_without_page_token_sets_error(rec, status):
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 2)))
    d.fail_next = [http_error(status, "bad")]
    assert tick()["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error"
    assert st["error"] == f"Drive rejected the query ({status})"
    assert st["cursor"] == "2026-09" and st["pageToken"] is None
    assert tick() == {"skipped": "idle"}
    backfill.resume(ACC)
    assert tick()["imported"] == 2


# ------------------------------------------------- pause / cancel / budget

def test_pause_makes_tick_idle(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    assert backfill.pause(ACC)["status"] == "paused"
    d = fake(month_files(("2026-09", 2)))
    assert tick() == {"skipped": "idle"}
    assert d.list_calls == []
    assert backfill.resume(ACC)["status"] == "running"
    assert backfill.pause("nobody@x.com") is None
    assert backfill.resume("nobody@x.com") is None


def test_pause_during_tick_is_respected(rec):
    rec.hook = lambda r, f: backfill.pause(ACC) if len(r.ids) == 1 else None
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 5)))
    out = tick()
    assert out["imported"] == 1 and out["status"] == "paused"
    st = backfill.get(ACC)
    assert st["status"] == "paused" and st["imported"] == 1
    assert st["pageDone"] == ["2026-09-04"]
    backfill.resume(ACC)
    assert tick()["imported"] == 4


def test_cancel_deletes_state(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    assert backfill.cancel(ACC) is True
    assert backfill.get(ACC) is None
    assert backfill.cancel(ACC) is False


def test_cancel_mid_tick_reports_cancelled(rec):
    rec.hook = lambda r, f: backfill.cancel(ACC)
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 3)))
    out = tick()
    assert out == {"skipped": "cancelled", "account": ACC}
    assert backfill.get(ACC) is None and len(rec.ids) == 1


def test_cancel_and_restart_during_tick_keeps_new_state(rec):
    fresh: dict = {}

    def hook(r, f):
        if len(r.ids) == 2:
            backfill.cancel(ACC)
            fresh.update(backfill.start(ACC, since=date(2026, 6, 1)))

    rec.hook = hook
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 30)))
    assert tick()["skipped"] == "cancelled"
    assert len(rec.ids) == 2
    st = backfill.get(ACC)
    assert st["startedAt"] == fresh["startedAt"] and st["since"] == "2026-06-01"
    assert st["cursor"] == "2026-09" and st["pageToken"] is None and st["pageDone"] == []
    assert (st["imported"], st["skipped"], st["failed"]) == (0, 0, 0)
    assert st["status"] == "running" and st["error"] is None


def test_auth_failure_after_restart_does_not_touch_new_state(rec):
    def hook(r, f):
        backfill.cancel(ACC)
        backfill.start(ACC, since=date(2026, 6, 1))

    rec.hook = hook
    rec.outcomes = {"2026-09-02": GdriveAuthError("revoked")}  # the first file
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 3)))
    assert tick()["skipped"] == "cancelled"
    st = backfill.get(ACC)
    assert st["status"] == "running" and st["error"] is None


def test_tick_budget_stops_mid_page_and_next_tick_continues(rec, monkeypatch):
    assert backfill.TICK_BUDGET_SECONDS == 60
    clock = {"t": 1000.0}
    monkeypatch.setattr(backfill, "_monotonic", lambda: clock["t"])
    rec.hook = lambda r, f: clock.update(t=clock["t"] + 20.0)
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 30)))
    out = tick()
    assert out["imported"] == 3 and out["status"] == "running" and out["cursor"] == "2026-09"
    st = backfill.get(ACC)
    assert st["pageToken"] is None and len(st["pageDone"]) == 3

    rec.hook = None
    out = tick()
    assert d.list_calls[1]["pageToken"] is None
    assert out["imported"] == 25  # the per-tick cap, not the budget, stops it
    st = backfill.get(ACC)
    assert st["pageToken"] is None and st["imported"] == 28 and len(st["pageDone"]) == 28
    out = tick()
    assert d.list_calls[2]["pageToken"] is None
    assert out["imported"] == 2 and out["cursor"] == "2026-08"
    assert backfill.get(ACC)["pageDone"] == []
    assert len(rec.ids) == len(set(rec.ids)) == 30


def test_page_of_mostly_other_peoples_files_is_handled_in_one_tick(rec):
    backfill.start(ACC, since=date(2026, 8, 1))
    theirs = [drive_file(f"theirs-{i:02d}", modified=f"2026-09-20T10:{i:02d}:00.000Z",
                         owned=False, modified_by_me=False) for i in range(60)]
    d = fake(theirs + month_files(("2026-09", 5)))
    out = tick()
    assert out["imported"] == 5 and out["cursor"] == "2026-08"
    assert sorted(rec.ids) == [f"2026-09-{i:02d}" for i in range(5)]
    assert len(d.list_calls) == 1 and d.list_calls[0]["pageSize"] == 100


def test_processed_cap_stops_mid_page_and_next_tick_continues(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    d = fake(month_files(("2026-09", 40))
             + [drive_file(f"theirs-{i}", modified="2026-09-20T00:00:00.000Z",
                           owned=False, modified_by_me=False) for i in range(10)])
    out = tick()
    assert out["imported"] == 25 and out["status"] == "running" and out["cursor"] == "2026-09"
    st = backfill.get(ACC)
    assert st["pageToken"] is None and len(st["pageDone"]) == 25 and st["error"] is None
    out = tick()
    assert d.list_calls[1]["pageToken"] is None
    assert out["imported"] == 15 and out["status"] == "done"
    assert len(rec.ids) == len(set(rec.ids)) == 40
    assert backfill.get(ACC)["pageDone"] == []


def test_batch_size_caps_processed_files(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 10)))
    assert backfill.run_tick(batch_size=4)["imported"] == 4
    assert backfill.run_tick(batch_size=4)["imported"] == 4
    out = backfill.run_tick(batch_size=4)
    assert out["imported"] == 2 and out["status"] == "done"


def test_tick_budget_on_last_file_advances_page(rec, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(backfill, "_monotonic", lambda: clock["t"])
    rec.hook = lambda r, f: clock.update(t=clock["t"] + 100.0)
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 2)))
    out = tick()
    assert out["imported"] == 1 and out["cursor"] == "2026-09"
    out = tick()
    assert out["imported"] == 1 and out["status"] == "done"


# -------------------------------------------------------- AI-routing pause

def test_ai_routing_unavailable_pauses_after_five_fallbacks(rec):
    rec.fallbacks = True
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 10)))
    out = tick()
    assert len(rec.ids) == 5
    assert out["status"] == "error" and out["imported"] == 5
    st = backfill.get(ACC)
    assert st["error"] == backfill.ROUTING_ERROR_MESSAGE == "AI routing unavailable — resume later"
    assert st["routingFallbacks"] == 5
    assert tick() == {"skipped": "idle"}

    st = backfill.resume(ACC)
    assert st["status"] == "running" and st["routingFallbacks"] == 0
    rec.fallbacks = False
    out = tick()
    assert out["imported"] == 5 and out["status"] == "done"
    assert len(rec.ids) == len(set(rec.ids)) == 10


def test_routing_counter_resets_on_success_and_spans_ticks(rec):
    # 4 per page: [F F F F] [S F F F] [F F ...] → pause on the 2nd file of tick 3
    rec.fallbacks = [True] * 4 + [False] + [True] * 7
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 12)))
    assert backfill.run_tick(batch_size=4)["status"] == "running"
    assert backfill.get(ACC)["routingFallbacks"] == 4
    assert backfill.run_tick(batch_size=4)["status"] == "running"
    assert backfill.get(ACC)["routingFallbacks"] == 3
    assert backfill.run_tick(batch_size=4)["status"] == "error"
    assert len(rec.ids) == 10


def test_updated_and_skipped_leave_streak_alone(rec):
    rec.fallbacks = True
    rec.outcomes = {"2026-09-02": "updated", "2026-09-04": "skipped", "2026-09-05": "failed"}
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 8)))
    out = tick()
    # files 07,06 (F,F) then 05 failed, 04 skipped, 03 F, 02 updated, 01 F → 4 → 00 F = 5
    assert out["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error" and st["routingFallbacks"] == 5
    assert len(rec.ids) == 8


def test_routing_pause_survives_budget_stop(rec, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(backfill, "_monotonic", lambda: clock["t"])
    rec.fallbacks = True
    rec.hook = lambda r, f: clock.update(t=clock["t"] + 12.0)
    backfill.start(ACC, since=date(2026, 9, 1))
    fake(month_files(("2026-09", 10)))
    assert tick()["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error" and st["error"] == backfill.ROUTING_ERROR_MESSAGE


# -------------------------------------------------------- scheduling guards

def test_removed_account_cancels_disabled_account_skips(rec):
    backfill.start(ACC, since=date(2026, 9, 1))
    backfill.start(ACC2, since=date(2026, 9, 1))
    write_accounts([{"connector": "gdrive", "id": ACC2, "enabled": False}])
    assert tick() == {"skipped": "idle"}
    assert backfill.get(ACC) is None
    assert backfill.get(ACC2)["status"] == "running"
    write_accounts([{"connector": "gdrive", "id": ACC2}])
    assert tick()["account"] == ACC2


def test_malformed_registry_leaves_state(rec, v, monkeypatch):
    backfill.start(ACC, since=date(2026, 9, 1))
    (v / "90-meta" / "accounts.yaml").write_text("accounts: {broken: [", encoding="utf-8")
    assert tick() == {"skipped": "idle"}
    assert (state_dir() / STATE).exists()

    def boom(*a, **kw):
        raise ValueError("bad registry")

    monkeypatch.setattr(backfill.accounts, "list_accounts", boom)
    assert tick() == {"skipped": "idle"}
    assert (state_dir() / STATE).exists()


def test_two_accounts_alternate(rec):
    backfill.start(ACC, since=date(2026, 1, 1))
    backfill.start(ACC2, since=date(2026, 1, 1))
    seen = [tick()["account"] for _ in range(4)]
    assert seen == [ACC, ACC2, ACC, ACC2]


def test_get_reports_months_progress(rec):
    assert backfill.get(ACC) is None
    backfill.start(ACC, since=date(2026, 6, 15))
    st = backfill.get(ACC)
    assert st["monthsTotal"] == 4 and st["monthsDone"] == 0
    tick()
    tick()
    st = backfill.get(ACC)
    assert st["cursor"] == "2026-07" and st["monthsDone"] == 2
    tick()
    tick()
    st = backfill.get(ACC)
    assert st["status"] == "done" and st["monthsDone"] == 4


def test_get_unreadable_state_is_none():
    p = state_dir() / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert backfill.get(ACC) is None


# ----------------------------------------------------------------- estimate

def test_estimate_counts_only_mine():
    d = fake(month_files(("2026-09", 3), ("2026-06", 2))
             + [drive_file("theirs", modified="2026-08-01T00:00:00.000Z",
                           owned=False, modified_by_me=False),
                drive_file("edited", modified="2026-08-01T00:00:00.000Z",
                           owned=False, modified_by_me=True),
                drive_file("old", modified="2025-01-01T00:00:00.000Z")])
    assert backfill.estimate(ACC, since=date(2026, 1, 1)) == {"files": 6, "capped": False}
    call = d.list_calls[0]
    assert call["pageSize"] == 1000
    assert call["fields"] == "nextPageToken,files(id,ownedByMe,modifiedByMe)"
    assert "modifiedTime > '2025-12-31T23:59:59'" in call["q"]


def test_estimate_pages_and_caps(monkeypatch):
    monkeypatch.setattr(backfill, "ESTIMATE_CAP", 5)
    files = [drive_file(f"f{i}", modified=f"2026-09-{i + 1:02d}T00:00:00.000Z") for i in range(8)]
    d = fake(files)
    real = drive.list_page

    def small_pages(drv, **kw):
        kw["page_size"] = 3
        return real(drv, **kw)

    monkeypatch.setattr(drive, "list_page", small_pages)
    assert backfill.estimate(ACC, since=date(2026, 1, 1)) == {"files": 5, "capped": True}
    assert len(d.list_calls) == 2
    monkeypatch.setattr(backfill, "ESTIMATE_CAP", 100)
    assert backfill.estimate(ACC, since=date(2026, 1, 1)) == {"files": 8, "capped": False}


def test_estimate_propagates_auth_and_api_disabled():
    from google.auth.exceptions import RefreshError

    d = fake([])
    d.fail_next = [http_error(401, "authError")]
    with pytest.raises(GdriveAuthError):
        backfill.estimate(ACC, since=date(2026, 1, 1))
    d.fail_next = [RefreshError("invalid_grant")]
    with pytest.raises(GdriveAuthError):
        backfill.estimate(ACC, since=date(2026, 1, 1))
    d.fail_next = [http_error(403, "accessNotConfigured")]
    with pytest.raises(drive.DriveApiDisabled):
        backfill.estimate(ACC, since=date(2026, 1, 1))
    DRIVES[ACC] = GdriveAuthError("no token")
    with pytest.raises(GdriveAuthError):
        backfill.estimate(ACC, since=date(2026, 1, 1))
