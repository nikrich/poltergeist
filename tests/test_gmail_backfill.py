"""Gmail backfill job: month cursor, paging, dedup, resume, round-robin."""
from __future__ import annotations

import itertools
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from ghostbrain.connectors.gmail import backfill
from ghostbrain.connectors.gmail.auth import GmailAuthError
from ghostbrain.paths import state_dir, vault_path

TODAY = date(2026, 9, 28)
ACC = "a@x.com"
ACC2 = "b@x.com"


# ------------------------------------------------------------------ fixtures

def write_accounts(entries: list[dict]) -> None:
    (vault_path() / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def v(monkeypatch) -> Path:
    root = vault_path()
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, agencyx]\n"
        "gmail:\n  denylist_domains: ['*.spam.com']\n  relevance_gate: false\n",
        encoding="utf-8",
    )
    write_accounts([{"connector": "gmail", "id": ACC}, {"connector": "gmail", "id": ACC2}])
    monkeypatch.setattr(backfill, "_today", lambda: TODAY)
    clock = itertools.count()
    base = datetime(2026, 9, 28, 12, tzinfo=UTC)
    monkeypatch.setattr(backfill, "_now", lambda: base + timedelta(seconds=next(clock)))
    return root


def thread(tid: str, *, sender: str = "bob@ok.com", labels: tuple = ()) -> dict:
    return {
        "id": tid,
        "messages": [{
            "threadId": tid, "internalDate": "1790000000000", "labelIds": list(labels),
            "payload": {"headers": [{"name": "Subject", "value": f"subject {tid}"},
                                    {"name": "From", "value": f"Bob <{sender}>"}]},
        }],
    }


EXECUTE_RETRIES: list[int] = []


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries=0):
        EXECUTE_RETRIES.append(num_retries)
        return self._fn()


def http_error(status: int):
    import httplib2
    from googleapiclient.errors import HttpError

    return HttpError(httplib2.Response({"status": status}), b"{}")


class FakeGmail:
    """Minimal users().threads().list/get with month-scoped queries."""

    def __init__(self, threads_by_month: dict[str, list[dict]], page_size: int = 100):
        self.months = threads_by_month
        self.page_size = page_size
        self.by_id = {t["id"]: t for ts in threads_by_month.values() for t in ts}
        self.list_calls: list[dict] = []
        self.get_errors: dict[str, BaseException] = {}
        self.list_error: BaseException | None = None

    def users(self):
        return self

    def threads(self):
        return self

    def list(self, *, userId, q, maxResults, pageToken=None):
        assert userId == "me"
        self.list_calls.append({"q": q, "maxResults": maxResults, "pageToken": pageToken})

        def run():
            if self.list_error is not None:
                raise self.list_error
            after = re.search(r"after:(\d{4})/(\d{2})/(\d{2})", q)
            before = re.search(r"before:(\d{4})/(\d{2})/(\d{2})", q)
            a = date(*map(int, after.groups()))
            b = date(*map(int, before.groups())) if before else date(9999, 1, 1)
            items = [
                t for key in sorted(self.months, reverse=True)
                if a <= date(int(key[:4]), int(key[5:]), 1) < b
                for t in self.months[key]
            ]
            start = int(pageToken or 0)
            n = min(maxResults, self.page_size)
            page = items[start:start + n]
            out = {"threads": [{"id": t["id"]} for t in page],
                   "resultSizeEstimate": len(items)}
            if start + n < len(items):
                out["nextPageToken"] = str(start + n)
            if not page:
                out.pop("threads")
            return out

        return _Req(run)

    def get(self, *, userId, id, format):
        assert userId == "me" and format == "full"

        def run():
            if id in self.get_errors:
                raise self.get_errors[id]
            return self.by_id[id]

        return _Req(run)


class Recorder:
    """process() stub that writes a note like the real pipeline would."""

    def __init__(self, crash_after: int | None = None, fail_ids: tuple = ()):
        self.events: list[dict] = []
        self.crash_after = crash_after
        self.fail_ids = fail_ids

    def __call__(self, event: dict) -> dict:
        if self.crash_after is not None and len(self.events) >= self.crash_after:
            raise Crash()
        tid = event["metadata"]["thread_id"]
        if tid in self.fail_ids:
            raise RuntimeError("boom")
        self.events.append(event)
        d = vault_path() / "20-contexts" / "personal" / "gmail"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tid}.md").write_text(f"---\nid: {event['id']}\n---\nbody\n", encoding="utf-8")
        return {"status": "ok"}

    @property
    def ids(self) -> list[str]:
        return [e["metadata"]["thread_id"] for e in self.events]


class Crash(BaseException):
    """Simulated process kill mid-page."""


def tick(fake, proc, **kw):
    return backfill.run_tick(service_factory=lambda acc: fake, process=proc, **kw)


def months_of(*keys_counts) -> dict[str, list[dict]]:
    out = {}
    for key, n in keys_counts:
        out[key] = [thread(f"{key}-{i}") for i in range(n)]
    return out


# --------------------------------------------------------------------- tests

def test_start_creates_running_state_and_is_idempotent():
    st = backfill.start(ACC, since=date(2025, 9, 28))
    assert st["status"] == "running"
    assert st["account"] == ACC
    assert st["since"] == "2025-09-28"
    assert st["cursor"] == "2026-09"
    assert st["pageToken"] is None
    assert (st["imported"], st["skipped"], st["failed"]) == (0, 0, 0)
    assert st["error"] is None
    assert (state_dir() / "gmail_backfill.a_at_x_com.json").exists()

    again = backfill.start(ACC, since=date(2020, 1, 1))
    assert again == st

    with pytest.raises(KeyError):
        backfill.start("nobody@x.com", since=date(2025, 1, 1))


def test_start_after_done_restarts():
    path = state_dir() / "gmail_backfill.a_at_x_com.json"
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail({})
    tick(fake, Recorder())
    assert backfill.get(ACC)["status"] == "done"
    st = backfill.start(ACC, since=date(2026, 8, 1))
    assert st["status"] == "running" and st["since"] == "2026-08-01"
    assert path.exists()


def test_since_clamped_to_ten_years():
    st = backfill.start(ACC, since=date(1999, 1, 1))
    assert st["since"] == "2016-09-28"


def test_tick_imports_batch_and_persists_counts():
    backfill.start(ACC, since=date(2026, 1, 1))
    fake = FakeGmail(months_of(("2026-09", 30)))
    proc = Recorder()
    out = tick(fake, proc)
    assert out == {"account": ACC, "status": "running", "imported": 25, "skipped": 0,
                   "failed": 0, "cursor": "2026-09"}
    assert len(proc.events) == 25
    assert proc.events[0]["metadata"]["accountId"] == ACC
    q = fake.list_calls[0]["q"]
    assert q == (backfill.QUERY_BASE + " after:2026/09/01 before:2026/10/01")
    assert fake.list_calls[0]["maxResults"] == 25
    st = backfill.get(ACC)
    assert st["imported"] == 25
    assert st["pageToken"] == "25"


def test_paging_uses_page_token_then_steps_month_back():
    backfill.start(ACC, since=date(2026, 1, 1))
    fake = FakeGmail(months_of(("2026-09", 30), ("2026-08", 3)))
    proc = Recorder()
    tick(fake, proc)
    out = tick(fake, proc)
    assert fake.list_calls[1]["pageToken"] == "25"
    assert out["imported"] == 5 and out["cursor"] == "2026-08"
    st = backfill.get(ACC)
    assert st["pageToken"] is None and st["imported"] == 30
    out = tick(fake, proc)
    assert "after:2026/08/01 before:2026/09/01" in fake.list_calls[2]["q"]
    assert out["imported"] == 3 and out["cursor"] == "2026-07"


def test_empty_month_steps_back():
    backfill.start(ACC, since=date(2026, 1, 1))
    fake = FakeGmail({})
    out = tick(fake, Recorder())
    assert out["cursor"] == "2026-08" and out["status"] == "running"
    assert out["imported"] == 0


def test_december_to_january_boundaries(monkeypatch):
    monkeypatch.setattr(backfill, "_today", lambda: date(2027, 1, 10))
    backfill.start(ACC, since=date(2026, 1, 1))
    fake = FakeGmail({})
    tick(fake, Recorder())
    assert "after:2027/01/01 before:2027/02/01" in fake.list_calls[0]["q"]
    assert backfill.get(ACC)["cursor"] == "2026-12"
    tick(fake, Recorder())
    assert "after:2026/12/01 before:2027/01/01" in fake.list_calls[1]["q"]


def test_done_after_since():
    backfill.start(ACC, since=date(2026, 8, 15))
    fake = FakeGmail(months_of(("2026-09", 1), ("2026-08", 1), ("2026-07", 1)))
    proc = Recorder()
    assert tick(fake, proc)["status"] == "running"
    out = tick(fake, proc)
    assert out["status"] == "done"
    assert proc.ids == ["2026-09-0", "2026-08-0"]
    assert tick(fake, proc) == {"skipped": "idle"}


def test_existing_note_skipped(v):
    d = v / "20-contexts" / "personal" / "gmail"
    d.mkdir(parents=True)
    (d / "old.md").write_text("---\nid: gmail:thread:2026-09-1\n---\nx\n", encoding="utf-8")
    inbox = v / "00-inbox" / "raw" / "gmail"
    inbox.mkdir(parents=True)
    (inbox / "old2.md").write_text("---\nid: gmail:thread:2026-09-2\n---\nx\n", encoding="utf-8")
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 4)))
    proc = Recorder()
    out = tick(fake, proc)
    assert out["imported"] == 2 and out["skipped"] == 2
    assert proc.ids == ["2026-09-0", "2026-09-3"]


def test_denylisted_and_promotional_skipped():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail({"2026-09": [
        thread("ok"),
        thread("deny", sender="news@mail.spam.com"),
        thread("promo", labels=("CATEGORY_PROMOTIONS",)),
        {"id": "empty", "messages": []},
    ]})
    proc = Recorder()
    out = tick(fake, proc)
    assert proc.ids == ["ok"]
    assert out["imported"] == 1 and out["skipped"] == 3


def test_thread_error_counts_failed_and_continues(caplog):
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 4)))
    fake.get_errors["2026-09-0"] = RuntimeError("http 500")
    proc = Recorder(fail_ids=("2026-09-2",))
    with caplog.at_level("WARNING"):
        out = tick(fake, proc)
    assert out["failed"] == 2 and out["imported"] == 2
    assert proc.ids == ["2026-09-1", "2026-09-3"]
    assert "2026-09-0" in caplog.text
    assert backfill.get(ACC)["failed"] == 2


def test_auth_error_sets_error_then_resume():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 2)))
    fake.list_error = GmailAuthError("refresh token rejected")
    out = tick(fake, Recorder())
    assert out["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error" and st["error"] == "needs re-auth"
    assert st["cursor"] == "2026-09"
    assert tick(fake, Recorder()) == {"skipped": "idle"}

    st = backfill.resume(ACC)
    assert st["status"] == "running" and st["error"] is None
    fake.list_error = None
    proc = Recorder()
    assert tick(fake, proc)["imported"] == 2

    def bad_factory(acc):
        raise GmailAuthError("no token")

    backfill.cancel(ACC)
    backfill.start(ACC, since=date(2026, 9, 1))
    out = backfill.run_tick(service_factory=bad_factory, process=Recorder())
    assert out["status"] == "error"


def test_resume_after_crash_mid_page():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 5)))
    crashing = Recorder(crash_after=2)
    with pytest.raises(Crash):
        tick(fake, crashing)
    st = backfill.get(ACC)
    assert st["imported"] == 2 and st["pageToken"] is None and st["cursor"] == "2026-09"

    proc = Recorder()
    out = tick(fake, proc)
    assert out["skipped"] == 2 and out["imported"] == 3
    all_ids = crashing.ids + proc.ids
    assert sorted(all_ids) == sorted(set(all_ids)) and len(all_ids) == 5
    assert backfill.get(ACC)["imported"] == 5


def test_pause_makes_tick_idle():
    backfill.start(ACC, since=date(2026, 9, 1))
    st = backfill.pause(ACC)
    assert st["status"] == "paused"
    fake = FakeGmail(months_of(("2026-09", 2)))
    assert tick(fake, Recorder()) == {"skipped": "idle"}
    assert fake.list_calls == []
    assert backfill.resume(ACC)["status"] == "running"
    assert backfill.pause("nobody@x.com") is None
    assert backfill.resume("nobody@x.com") is None


def test_pause_during_tick_is_respected():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 5)))
    inner = Recorder()

    def proc(event):
        inner(event)
        if len(inner.events) == 2:
            backfill.pause(ACC)
        return {"status": "ok"}

    out = tick(fake, proc)
    assert out["imported"] == 2 and out["status"] == "paused"
    st = backfill.get(ACC)
    assert st["status"] == "paused" and st["imported"] == 2


def test_cancel_deletes_state_keeps_notes(v):
    backfill.start(ACC, since=date(2026, 9, 1))
    tick(FakeGmail(months_of(("2026-09", 2))), Recorder())
    notes = list((v / "20-contexts" / "personal" / "gmail").glob("*.md"))
    assert len(notes) == 2
    assert backfill.cancel(ACC) is True
    assert backfill.get(ACC) is None
    assert backfill.cancel(ACC) is False
    assert all(n.exists() for n in notes)


def test_removed_account_cancels_disabled_account_skips():
    backfill.start(ACC, since=date(2026, 9, 1))
    backfill.start(ACC2, since=date(2026, 9, 1))
    write_accounts([{"connector": "gmail", "id": ACC2, "enabled": False}])
    fake = FakeGmail(months_of(("2026-09", 2)))
    assert tick(fake, Recorder()) == {"skipped": "idle"}
    assert backfill.get(ACC) is None
    assert backfill.get(ACC2)["status"] == "running"

    write_accounts([{"connector": "gmail", "id": ACC2}])
    assert tick(fake, Recorder())["account"] == ACC2


def test_two_accounts_alternate():
    backfill.start(ACC, since=date(2026, 1, 1))
    backfill.start(ACC2, since=date(2026, 1, 1))
    fake = FakeGmail({})
    seen = [tick(fake, Recorder())["account"] for _ in range(4)]
    assert seen == [ACC, ACC2, ACC, ACC2]


def test_estimate_returns_result_size():
    fake = FakeGmail(months_of(("2026-09", 3), ("2026-06", 2), ("2025-01", 7)))
    n = backfill.estimate(ACC, since=date(2026, 1, 1), service_factory=lambda a: fake)
    assert n == 5
    assert fake.list_calls[0]["q"] == backfill.QUERY_BASE + " after:2026/01/01"
    assert fake.list_calls[0]["maxResults"] == 1

    fake.list_error = GmailAuthError("x")
    with pytest.raises(GmailAuthError):
        backfill.estimate(ACC, since=date(2026, 1, 1), service_factory=lambda a: fake)


def test_get_reports_months_progress():
    assert backfill.get(ACC) is None
    backfill.start(ACC, since=date(2026, 6, 15))
    st = backfill.get(ACC)
    assert st["monthsTotal"] == 4 and st["monthsDone"] == 0
    fake = FakeGmail({})
    tick(fake, Recorder())
    tick(fake, Recorder())
    st = backfill.get(ACC)
    assert st["cursor"] == "2026-07" and st["monthsDone"] == 2
    tick(fake, Recorder())
    tick(fake, Recorder())
    st = backfill.get(ACC)
    assert st["status"] == "done" and st["monthsDone"] == 4


def test_get_unreadable_state_is_none():
    p = state_dir() / "gmail_backfill.a_at_x_com.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert backfill.get(ACC) is None


# ------------------------------------------------ fix round 1: failure modes

def test_http_401_on_list_needs_reauth():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 2)))
    fake.list_error = http_error(401)
    out = tick(fake, Recorder())
    assert out["status"] == "error"
    st = backfill.get(ACC)
    assert st["status"] == "error" and st["error"] == "needs re-auth"


def test_refresh_error_on_get_needs_reauth():
    from google.auth.exceptions import RefreshError

    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 3)))
    fake.get_errors["2026-09-1"] = RefreshError("invalid_grant")
    proc = Recorder()
    out = tick(fake, proc)
    assert out["status"] == "error" and out["failed"] == 0
    assert proc.ids == ["2026-09-0"]
    st = backfill.get(ACC)
    assert st["error"] == "needs re-auth" and st["failed"] == 0


def test_http_503_on_list_keeps_running_and_moves_on():
    backfill.start(ACC, since=date(2026, 9, 1))
    backfill.start(ACC2, since=date(2026, 9, 1))
    fakes = {ACC: FakeGmail(months_of(("2026-09", 2))), ACC2: FakeGmail({})}
    fakes[ACC].list_error = http_error(503)
    proc = Recorder()

    def run():
        return backfill.run_tick(service_factory=lambda a: fakes[a], process=proc)

    before = backfill.get(ACC)["updatedAt"]
    out = run()
    assert out["account"] == ACC and out["status"] == "running"
    st = backfill.get(ACC)
    assert st["status"] == "running" and st["error"] == "HttpError"
    assert st["updatedAt"] > before
    assert st["cursor"] == "2026-09" and st["pageToken"] is None

    assert run()["account"] == ACC2  # round-robin moved on

    fakes[ACC].list_error = None
    out = run()
    assert out["account"] == ACC and out["imported"] == 2
    assert backfill.get(ACC)["error"] is None


def test_os_error_on_list_is_transient():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail({})
    fake.list_error = TimeoutError("timed out")
    out = tick(fake, Recorder())
    assert out["status"] == "running"
    assert backfill.get(ACC)["error"] == "TimeoutError"


def test_transient_get_error_stops_tick_and_retries_page():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 5)))
    fake.get_errors["2026-09-2"] = http_error(503)
    first = Recorder()
    out = tick(fake, first)
    assert out == {"account": ACC, "status": "running", "imported": 2, "skipped": 0,
                   "failed": 0, "cursor": "2026-09"}
    st = backfill.get(ACC)
    assert st["failed"] == 0 and st["pageToken"] is None and st["error"] == "HttpError"

    del fake.get_errors["2026-09-2"]
    second = Recorder()
    out = tick(fake, second)
    assert out["skipped"] == 2 and out["imported"] == 3 and out["cursor"] == "2026-08"
    all_ids = first.ids + second.ids
    assert len(all_ids) == 5 and len(set(all_ids)) == 5
    st = backfill.get(ACC)
    assert st["imported"] == 5 and st["error"] is None


def test_404_on_get_counts_failed_and_continues():
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 3)))
    fake.get_errors["2026-09-1"] = http_error(404)
    proc = Recorder()
    out = tick(fake, proc)
    assert out["failed"] == 1 and out["imported"] == 2
    assert proc.ids == ["2026-09-0", "2026-09-2"]


def test_every_execute_uses_num_retries():
    EXECUTE_RETRIES.clear()
    backfill.start(ACC, since=date(2026, 9, 1))
    fake = FakeGmail(months_of(("2026-09", 2)))
    tick(fake, Recorder())
    backfill.estimate(ACC, since=date(2026, 1, 1), service_factory=lambda a: fake)
    assert len(EXECUTE_RETRIES) == 4
    assert set(EXECUTE_RETRIES) == {3}


def test_estimate_maps_http_401_to_auth_error():
    fake = FakeGmail({})
    fake.list_error = http_error(401)
    with pytest.raises(GmailAuthError):
        backfill.estimate(ACC, since=date(2026, 1, 1), service_factory=lambda a: fake)


def test_malformed_registry_leaves_state(v):
    backfill.start(ACC, since=date(2026, 9, 1))
    (v / "90-meta" / "accounts.yaml").write_text("accounts: {broken: [", encoding="utf-8")
    fake = FakeGmail(months_of(("2026-09", 1)))
    assert tick(fake, Recorder()) == {"skipped": "idle"}
    assert (state_dir() / "gmail_backfill.a_at_x_com.json").exists()
    (v / "90-meta" / "accounts.yaml").write_text("just a string\n", encoding="utf-8")
    assert tick(fake, Recorder()) == {"skipped": "idle"}
    assert (state_dir() / "gmail_backfill.a_at_x_com.json").exists()


def test_crlf_note_is_deduped(v):
    d = v / "20-contexts" / "personal" / "gmail"
    d.mkdir(parents=True)
    (d / "old.md").write_bytes(b"---\r\nid: gmail:thread:2026-09-0\r\n---\r\nx\r\n")
    backfill.start(ACC, since=date(2026, 9, 1))
    proc = Recorder()
    out = tick(FakeGmail(months_of(("2026-09", 2))), proc)
    assert out["skipped"] == 1 and proc.ids == ["2026-09-1"]


def test_cancel_mid_tick_reports_skipped_cancelled():
    backfill.start(ACC, since=date(2026, 9, 1))
    inner = Recorder()

    def proc(event):
        inner(event)
        backfill.cancel(ACC)
        return {"status": "ok"}

    out = tick(FakeGmail(months_of(("2026-09", 3))), proc)
    assert out["skipped"] == "cancelled"
    assert "status" not in out
    assert backfill.get(ACC) is None
