import pytest
from ghostbrain.api.auth.providers.ms_device_code import MicrosoftProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    return tmp_path


def _sess():
    return Session(id="s", connector_id="outlook_mail", status="pending", next=NextAction(kind="need_input"))


def test_start_needs_app_config_when_missing(vault):
    action = MicrosoftProvider().start("outlook_mail", {})
    names = {f["name"] for f in (action.fields or [])}
    assert {"client_id", "tenant_id"} <= names


def test_submit_app_config_then_shows_device_code(vault, monkeypatch):
    import ghostbrain.api.auth.providers.ms_device_code as mod

    class FakeApp:
        def initiate_device_flow(self, scopes):
            return {"user_code": "ABCD-EFGH", "verification_uri": "https://microsoft.com/devicelogin",
                    "message": "go", "device_code": "dev", "expires_in": 900, "interval": 5}
    monkeypatch.setattr(mod, "_build_app", lambda cfg: FakeApp())
    p = MicrosoftProvider()
    sess = _sess()
    action = p.submit("outlook_mail", sess, {"client_id": "cid", "tenant_id": "tid"})
    assert action.kind == "show_device_code"
    assert action.user_code == "ABCD-EFGH"


def test_poll_success_sets_account(vault, monkeypatch):
    import ghostbrain.api.auth.providers.ms_device_code as mod

    class FakeApp:
        def acquire_token_by_device_flow(self, flow):
            return {"access_token": "t"}

        def get_accounts(self):
            return [{"username": "me@corp.com"}]

    monkeypatch.setattr(mod, "_build_app", lambda cfg: FakeApp())
    p = MicrosoftProvider()
    sess = _sess()
    sess._ms_flow = {"device_code": "dev"}  # type: ignore[attr-defined]
    p.poll("outlook_mail", sess)
    assert sess.status == "success"
    assert sess.account == "me@corp.com"


def test_poll_failure_sets_error_without_secret(vault, monkeypatch):
    import ghostbrain.api.auth.providers.ms_device_code as mod

    class FakeApp:
        def acquire_token_by_device_flow(self, flow):
            return {"error": "authorization_pending", "error_description": "nope"}

        def get_accounts(self):
            return []

    monkeypatch.setattr(mod, "_build_app", lambda cfg: FakeApp())
    p = MicrosoftProvider()
    sess = _sess()
    sess._ms_flow = {"device_code": "dev"}  # type: ignore[attr-defined]
    p.poll("outlook_mail", sess)
    assert sess.status == "error"
    assert sess.error == "nope"
    assert "t" != sess.error  # no bare access-token leaked into the error message
    assert "access_token" not in (sess.error or "")


class _SignInApp:
    """MSAL app double: a pre-existing cached sign-in plus the new one."""

    def __init__(self, cached):
        self._cached = cached

    def acquire_token_by_device_flow(self, flow):
        return {"access_token": "t", "id_token_claims": {"preferred_username": "new@corp.com"}}

    def get_accounts(self, username=None):
        return [{"username": u} for u in self._cached]


def _poll_with(monkeypatch, cached):
    import ghostbrain.api.auth.providers.ms_device_code as mod
    from ghostbrain.connectors.microsoft.graph import auth

    app = _SignInApp(cached)
    monkeypatch.setattr(mod, "_build_app", lambda cfg: app)
    monkeypatch.setattr(auth, "_build_app", lambda cfg, tenant_id=None: app)
    sess = _sess()
    sess._ms_flow = {"device_code": "dev"}  # type: ignore[attr-defined]
    MicrosoftProvider().poll("outlook_mail", sess)
    assert sess.status == "success"


def test_poll_first_sign_in_also_registers_existing_cached_accounts(vault, monkeypatch):
    """Registering only the new account would turn off the no-accounts
    fallback and silently stop syncing the pre-existing cached sign-in."""
    from ghostbrain import accounts

    _poll_with(monkeypatch, ["old@corp.com", "your account", "new@corp.com"])
    assert sorted(a.id for a in accounts.list_accounts("microsoft")) == ["new@corp.com", "old@corp.com"]


def test_poll_with_registered_accounts_does_not_adopt_cache(vault, monkeypatch):
    from ghostbrain import accounts

    accounts.ensure_account("microsoft", "reg@corp.com")
    _poll_with(monkeypatch, ["old@corp.com", "new@corp.com"])
    assert sorted(a.id for a in accounts.list_accounts("microsoft")) == ["new@corp.com", "reg@corp.com"]


def test_poll_adopting_cache_failure_is_non_fatal(vault, monkeypatch):
    import ghostbrain.api.auth.providers.ms_device_code as mod
    from ghostbrain import accounts
    from ghostbrain.connectors.microsoft.graph import auth

    app = _SignInApp(["new@corp.com"])
    monkeypatch.setattr(mod, "_build_app", lambda cfg: app)

    def boom(*a, **k):
        raise RuntimeError("keychain locked")

    monkeypatch.setattr(auth, "_build_app", boom)
    sess = _sess()
    sess._ms_flow = {"device_code": "dev"}  # type: ignore[attr-defined]
    MicrosoftProvider().poll("outlook_mail", sess)
    assert sess.status == "success"
    assert [a.id for a in accounts.list_accounts("microsoft")] == ["new@corp.com"]
