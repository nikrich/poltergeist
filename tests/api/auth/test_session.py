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
