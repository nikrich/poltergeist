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
