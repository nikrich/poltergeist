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
