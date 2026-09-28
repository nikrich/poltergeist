from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from ghostbrain import accounts_health
from ghostbrain.connectors.gdrive import connector as conn_mod
from ghostbrain.connectors.gdrive import drive, ingest, store
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.connector import GdriveConnector
from ghostbrain.paths import queue_dir, state_dir
from tests.gdrive_fakes import FakeDrive, drive_file, fake_services, http_error

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(drive, "_sleep", lambda s: None)


@pytest.fixture
def upserts(monkeypatch):
    seen = []

    def _upsert(event):
        seen.append(event["metadata"]["fileId"])
        return "imported", {"context": "work", "method": "account"}

    monkeypatch.setattr(store, "upsert", _upsert)
    return seen


def make(accounts, services_by_account):
    def services_for(email):
        svc = services_by_account[email]
        if isinstance(svc, Exception):
            raise svc
        return svc
    return GdriveConnector({"accounts": accounts}, queue_dir(), state_dir(),
                           services_for=services_for, now=lambda: NOW)


def _docs_drive(files):
    d = FakeDrive(files)
    for f in files:
        d.exports[f["id"]] = b"body"
    return d


def test_first_run_looks_back_seven_days_and_filters_mine(upserts):
    d = _docs_drive([
        drive_file("recent", modified=iso(NOW - timedelta(days=2))),
        drive_file("shared", modified=iso(NOW - timedelta(days=2)), owned=False, modified_by_me=False),
        drive_file("old", modified=iso(NOW - timedelta(days=9))),
    ])
    c = make(["me@x.com"], {"me@x.com": fake_services(drive=d)})
    assert c.run() == 1
    assert upserts == ["recent"]
    assert "modifiedTime > '2026-09-21T12:00:00'" in d.list_calls[0]["q"]


def test_debounce_defers_recent_edits_and_holds_cursor(upserts):
    hot = NOW - timedelta(minutes=5)
    d = _docs_drive([
        drive_file("hot", modified=iso(hot)),
        drive_file("cold", modified=iso(NOW - timedelta(hours=2))),
    ])
    c = make(["me@x.com"], {"me@x.com": fake_services(drive=d)})
    c.run()
    assert upserts == ["cold"] and c.stats["deferred"] == 1
    cursor = json.loads(conn_mod.cursor_path().read_text())["me@x.com"]
    assert drive.parse_time(cursor) < hot


def test_cursor_advances_to_run_start_when_nothing_deferred(upserts):
    d = _docs_drive([drive_file("a", modified=iso(NOW - timedelta(hours=3)))])
    make(["me@x.com"], {"me@x.com": fake_services(drive=d)}).run()
    assert json.loads(conn_mod.cursor_path().read_text())["me@x.com"] == NOW.isoformat()
    assert (state_dir() / "gdrive.last_run").exists()


def test_failing_account_keeps_its_cursor(upserts):
    ok = _docs_drive([drive_file("a", modified=iso(NOW - timedelta(hours=3)))])
    limited = FakeDrive()
    limited.fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    conn_mod.cursor_path().parent.mkdir(parents=True, exist_ok=True)
    old = (NOW - timedelta(days=1)).isoformat()
    conn_mod.cursor_path().write_text(json.dumps({"slow@x.com": old}))
    c = make(["me@x.com", "slow@x.com"],
             {"me@x.com": fake_services(drive=ok), "slow@x.com": fake_services(drive=limited)})
    c.run()
    cursors = json.loads(conn_mod.cursor_path().read_text())
    assert cursors["slow@x.com"] == old
    assert cursors["me@x.com"] == NOW.isoformat()
    assert accounts_health.health_for("gdrive", "slow@x.com")["status"] == accounts_health.STATUS_ERROR


def test_auth_failure_marks_account_auth_required(upserts):
    ok = _docs_drive([])
    c = make(["me@x.com", "bad@x.com"],
             {"me@x.com": fake_services(drive=ok), "bad@x.com": GdriveAuthError("revoked")})
    c.run()
    assert accounts_health.health_for("gdrive", "bad@x.com")["status"] == accounts_health.STATUS_AUTH


def test_all_accounts_failing_raises_and_saves_no_last_run(upserts):
    c = make(["bad@x.com"], {"bad@x.com": GdriveAuthError("revoked")})
    with pytest.raises(accounts_health.AllAccountsFailedError):
        c.run()
    assert not (state_dir() / "gdrive.last_run").exists()


def test_ingest_counts_failures_and_too_large(monkeypatch):
    d = FakeDrive()
    d.fail_next = [http_error(404, "notFound")]
    svc = fake_services(drive=d)
    assert ingest.ingest_file(svc, "me@x.com", drive_file("gone"), {}) == ("failed", False)
    big = drive_file("big", mime=drive.PDF, size=10**12)
    assert ingest.ingest_file(svc, "me@x.com", big, {}) == ("tooLarge", False)


def test_is_routing_fallback():
    assert ingest.is_routing_fallback({"method": "fallback", "context": "needs_review"})
    assert not ingest.is_routing_fallback({"method": "account", "context": "work"})
    assert not ingest.is_routing_fallback({"method": "path", "context": "needs_review"})
    assert not ingest.is_routing_fallback(None)


def test_ingest_reraises_auth_and_rate_limits():
    d = FakeDrive()
    d.fail_next = [http_error(401, "authError")]
    with pytest.raises(GdriveAuthError):
        ingest.ingest_file(fake_services(drive=d), "me@x.com", drive_file("a"), {})


def test_runner_skips_without_accounts():
    from ghostbrain.connectors.gdrive import runner
    result = runner.run()
    assert result.ok and result.skipped_reason == "not configured"


def test_scheduler_registers_gdrive_hourly():
    from ghostbrain import scheduler_jobs
    from ghostbrain.api.routes.connectors import SYNCABLE

    class Rec:
        def __init__(self):
            self.jobs = {}

        def add_job(self, name, schedule, fn, label):
            self.jobs[name] = (schedule, label)

        def add_daemon(self, *a, **k):
            pass

    r = Rec()
    scheduler_jobs.register_connectors(r)
    assert r.jobs["gdrive"][0].seconds == 3600
    assert "gdrive" in SYNCABLE


@pytest.mark.parametrize("exc", [OSError("net down"), TimeoutError("timed out"),
                                 ConnectionResetError("reset")])
def test_ingest_reraises_transient_network_errors(exc):
    import httplib2

    d = FakeDrive()
    d.fail_next = [exc]
    with pytest.raises(type(exc)):
        ingest.ingest_file(fake_services(drive=d), "me@x.com", drive_file("a"), {})
    d.fail_next = [httplib2.ServerNotFoundError("no dns")]
    with pytest.raises(httplib2.HttpLib2Error):
        ingest.ingest_file(fake_services(drive=d), "me@x.com", drive_file("a"), {})


def test_network_error_during_ingest_keeps_that_accounts_cursor(upserts, monkeypatch):
    from ghostbrain.connectors.gdrive import convert as convert_mod

    ok = _docs_drive([drive_file("a", modified=iso(NOW - timedelta(hours=3)))])
    flaky = _docs_drive([drive_file("b", modified=iso(NOW - timedelta(hours=3)))])
    real_convert = convert_mod.convert

    def convert(services, file):
        if file["id"] == "b":
            raise OSError("wifi dropped")
        return real_convert(services, file)

    monkeypatch.setattr(convert_mod, "convert", convert)
    conn_mod.cursor_path().parent.mkdir(parents=True, exist_ok=True)
    old = (NOW - timedelta(days=1)).isoformat()
    conn_mod.cursor_path().write_text(json.dumps({"flaky@x.com": old}))
    c = make(["me@x.com", "flaky@x.com"],
             {"me@x.com": fake_services(drive=ok), "flaky@x.com": fake_services(drive=flaky)})
    c.run()
    cursors = json.loads(conn_mod.cursor_path().read_text())
    assert cursors["flaky@x.com"] == old
    assert cursors["me@x.com"] == NOW.isoformat()
    assert c.stats["failed"] == 0
    assert accounts_health.health_for("gdrive", "flaky@x.com")["status"] == accounts_health.STATUS_ERROR
