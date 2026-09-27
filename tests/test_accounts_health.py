from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts_health as ah


class FakeAuthError(RuntimeError):
    pass


def test_for_each_account_isolates_failures_and_records_health():
    def fetch(acc: str) -> list[dict]:
        if acc == "expired@x.com":
            raise FakeAuthError("refresh token rejected")
        if acc == "flaky@x.com":
            raise TimeoutError("read timed out")
        return [{"id": f"ev-{acc}"}]

    events = ah.for_each_account(
        "gmail", ["ok@x.com", "expired@x.com", "flaky@x.com"], fetch,
        account_id=lambda a: a, auth_errors=(FakeAuthError,),
    )
    assert events == [{"id": "ev-ok@x.com"}]
    assert ah.health_for("gmail", "ok@x.com")["status"] == "ok"
    assert ah.health_for("gmail", "OK@X.com")["lastSuccessAt"] is not None
    expired = ah.health_for("gmail", "expired@x.com")
    assert expired["status"] == "auth_required"
    assert "refresh token rejected" in expired["error"]
    assert expired["lastSuccessAt"] is None
    assert ah.health_for("gmail", "flaky@x.com")["status"] == "error"
    assert ah.last_run_summary("gmail") == {
        "ok@x.com": "ok", "expired@x.com": "auth_required", "flaky@x.com": "error",
    }


def test_last_success_survives_a_later_failure():
    ah.record("slack", "acme", ah.STATUS_OK)
    first = ah.health_for("slack", "acme")["lastSuccessAt"]
    ah.record("slack", "acme", ah.STATUS_ERROR, "boom")
    h = ah.health_for("slack", "acme")
    assert h["status"] == "error" and h["lastSuccessAt"] == first and h["error"] == "boom"


def test_unreadable_health_file_is_treated_as_empty():
    p = ah.health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert ah.load_health() == {}
    ah.record("jira", "a.atlassian.net", ah.STATUS_OK)
    assert ah.health_for("jira", "a.atlassian.net")["status"] == "ok"


def test_run_connector_reports_accounts_and_all_failed(tmp_path: Path, monkeypatch):
    from ghostbrain.connectors import _runner

    class AllFail:
        def health_check(self) -> bool:
            return True

        def run(self) -> int:
            ah.for_each_account("gmail", ["a@x.com"], lambda a: 1 / 0, account_id=lambda a: a)
            return 0

    class OneOk:
        def health_check(self) -> bool:
            return True

        def run(self) -> int:
            ah.for_each_account("gmail", ["a@x.com"], lambda a: [{}], account_id=lambda a: a)
            return 1

    monkeypatch.setattr(_runner, "load_routing", dict)
    bad = _runner.run_connector("gmail", build=lambda r, q, s: AllFail())
    assert bad.ok is False and bad.error_type == "AllAccountsFailed"
    assert bad.details["accounts"] == {"a@x.com": "error"}

    good = _runner.run_connector("gmail", build=lambda r, q, s: OneOk())
    assert good.ok is True and good.queued == 1
    assert good.details == {"accounts": {"a@x.com": "ok"}}


def test_all_accounts_failing_raises_after_recording_every_health():
    import pytest

    def fetch(acc: str) -> list[dict]:
        if acc == "expired@x.com":
            raise FakeAuthError("refresh token rejected")
        raise TimeoutError("x" * 500)

    with pytest.raises(ah.AllAccountsFailedError) as exc:
        ah.for_each_account(
            "gmail", ["expired@x.com", "flaky@x.com"], fetch,
            account_id=lambda a: a, auth_errors=(FakeAuthError,),
        )
    msg = str(exc.value)
    assert msg.startswith("all gmail accounts failed: ")
    assert "expired@x.com: auth_required" in msg and "flaky@x.com: error" in msg
    assert "x" * 201 not in msg  # error snippets truncated to 200 chars
    assert ah.health_for("gmail", "expired@x.com")["status"] == "auth_required"
    assert ah.health_for("gmail", "flaky@x.com")["status"] == "error"
    assert ah.last_run_summary("gmail") == {"expired@x.com": "auth_required", "flaky@x.com": "error"}


def test_for_each_account_empty_items_returns_empty_without_raising():
    assert ah.for_each_account("gmail", [], lambda a: [{}], account_id=lambda a: a) == []
    assert ah.last_run_summary("gmail") == {}


def test_all_accounts_failed_does_not_advance_last_run(tmp_path: Path, monkeypatch):
    from datetime import datetime

    from ghostbrain.connectors import _runner
    from ghostbrain.connectors._base import Connector

    class Multi(Connector):
        name = "fakemulti"

        def __init__(self, fail: bool, *a, **kw):
            super().__init__(*a, **kw)
            self.fail = fail

        def health_check(self) -> bool:
            return True

        def fetch(self, since: datetime) -> list[dict]:
            def one(acc: str) -> list[dict]:
                if self.fail:
                    raise TimeoutError("graph down")
                return [{"id": f"ev-{acc}", "timestamp": "2026-01-01T00:00:00+00:00"}]
            return ah.for_each_account(self.name, ["a@x.com", "b@y.com"], one, account_id=lambda a: a)

        def normalize(self, raw: dict) -> dict:
            return raw

    monkeypatch.setattr(_runner, "load_routing", dict)
    state = tmp_path / "st"
    last_run = state / "fakemulti.last_run"

    res = _runner.run_connector("fakemulti", build=lambda r, q, s: Multi(True, {}, q, state))
    assert res.ok is False and res.error_type == "AllAccountsFailed"
    assert res.details == {"accounts": {"a@x.com": "error", "b@y.com": "error"}}
    assert "traceback" not in res.details
    assert not last_run.exists()

    ok = _runner.run_connector("fakemulti", build=lambda r, q, s: Multi(False, {}, q, state))
    assert ok.ok is True and ok.queued == 2
    before = last_run.read_text()

    again = _runner.run_connector("fakemulti", build=lambda r, q, s: Multi(True, {}, q, state))
    assert again.ok is False
    assert last_run.read_text() == before


def test_for_each_account_health_write_failure_is_best_effort(monkeypatch):
    import pytest

    def broken_record(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ah, "record", broken_record)
    # success still returns its events
    assert ah.for_each_account("gmail", ["ok@x.com"], lambda a: [{"id": a}],
                               account_id=lambda a: a) == [{"id": "ok@x.com"}]
    # the real per-account error still surfaces, not the OSError
    def fail(a):
        raise TimeoutError("read timed out")

    with pytest.raises(ah.AllAccountsFailedError, match="read timed out"):
        ah.for_each_account("gmail", ["bad@x.com"], fail, account_id=lambda a: a)
