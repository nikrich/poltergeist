import threading
import time
from ghostbrain.api.auth.session import AuthSessionManager, Session
from ghostbrain.api.auth.providers.base import NextAction


class FakeProvider:
    pattern = "fake"

    def start(self, connector_id, params):
        return NextAction(kind="need_input", fields=[{"name": "token", "label": "Token", "type": "password"}])

    def submit(self, connector_id, session, data):
        if data.get("token") == "good":
            session.status = "success"
            session.account = "fake@acct"
            return NextAction(kind="done")
        session.status = "error"
        session.error = "bad token"
        return NextAction(kind="need_input", fields=[])

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account


def test_start_returns_need_input():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    assert s.status == "waiting_input"
    assert s.next.kind == "need_input"
    assert m.status(s.id) is s


def test_submit_success():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    s2 = m.submit(s.id, FakeProvider(), {"token": "good"})
    assert s2.status == "success"
    assert s2.account == "fake@acct"


def test_submit_bad_token_errors_but_keeps_session():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    s2 = m.submit(s.id, FakeProvider(), {"token": "nope"})
    assert s2.status == "error"
    assert s2.error == "bad token"


def test_sweep_expires_old_sessions():
    m = AuthSessionManager()
    s = m.start("slack", FakeProvider(), {})
    m.sweep(now=s.created_at + 10_000, ttl_s=300)
    assert m.status(s.id) is None


class LongRunningSubmitProvider:
    """Mimics MS device-code: start() needs input, submit() transitions to a
    long-running kind (show_device_code) that must trigger a background poll.

    poll() blocks on `release` before finishing, so a test can call submit()
    again *while a poll is still in flight* to exercise the double-spawn guard
    (status is still "pending" at that point, so only the _poll_started flag
    - not the success/error status check - can prevent a second thread).
    """

    pattern = "longrunning"

    def __init__(self):
        self.poll_calls = 0
        self.poll_started = threading.Event()
        self.poll_ran = threading.Event()
        self.release = threading.Event()

    def start(self, connector_id, params):
        return NextAction(kind="need_input", fields=[{"name": "cid", "label": "Client ID", "type": "text"}])

    def submit(self, connector_id, session, data):
        return NextAction(kind="show_device_code", user_code="ABCD-EFGH", verification_uri="https://example.com")

    def poll(self, connector_id, session):
        self.poll_calls += 1
        self.poll_started.set()
        self.release.wait(timeout=2)
        session.status = "success"
        session.account = "polled@acct"
        self.poll_ran.set()

    def account_label(self, session):
        return session.account


def test_submit_transition_to_longrunning_spawns_poll():
    m = AuthSessionManager()
    provider = LongRunningSubmitProvider()
    s = m.start("outlook_mail", provider, {})
    assert s.status == "waiting_input"

    s2 = m.submit(s.id, provider, {"cid": "x"})
    assert s2.next.kind == "show_device_code"

    # poll() is now running on a background daemon thread but blocked on
    # `release`, so status is still "pending" here.
    assert provider.poll_started.wait(timeout=2), "poll() was never invoked after submit()"
    assert s2.status == "pending"

    # A client could plausibly retry submit() while the first poll is still in
    # flight (double-click, request retry). Since status is still "pending"
    # (neither success nor error), only the _poll_started guard - not the
    # status check - can prevent a second poll thread from spawning here.
    s3 = m.submit(s.id, provider, {"cid": "x"})
    assert s3.next.kind == "show_device_code"

    provider.release.set()  # let the (single) in-flight poll finish
    assert provider.poll_ran.wait(timeout=2), "poll() never completed"
    assert s3.status == "success"
    assert provider.poll_calls == 1, "poll() ran more than once - double-spawn guard failed"
