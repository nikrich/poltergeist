from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.dotenv_store import set_env
from ghostbrain.api.repo.routing import merge_routing


def _slug(site: str) -> str:
    return site.split(".", 1)[0].upper().replace("-", "_")


def _validate_myself(email: str, token: str, site: str) -> dict:
    from base64 import b64encode
    import requests

    cred = b64encode(f"{email}:{token}".encode()).decode()
    r = requests.get(
        f"https://{site}/rest/api/3/myself",
        headers={"Authorization": f"Basic {cred}", "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


class AtlassianTokenProvider:
    pattern = "atlassian_api"

    def start(self, connector_id, params):
        extra = []
        if connector_id == "confluence":
            extra = [{"name": "spaces", "label": "Space keys (comma-sep, optional)", "type": "text",
                      "placeholder": "DOCS, PROJ"}]
        return NextAction(
            kind="need_input",
            message="Create an Atlassian API token, then enter your email, the token, and your site.",
            fields=[
                {"name": "email", "label": "Atlassian email", "type": "text"},
                {"name": "token", "label": "API token", "type": "password"},
                {"name": "site", "label": "Site", "type": "text", "placeholder": "acme.atlassian.net"},
                *extra,
            ],
        )

    def submit(self, connector_id, session, data):
        email = (data.get("email") or "").strip()
        token = (data.get("token") or "").strip()
        site = (data.get("site") or "").strip().replace("https://", "").rstrip("/")
        if not (email and token and site):
            session.status = "error"; session.error = "Email, token and site are all required"
            return NextAction(kind="need_input", fields=[])
        try:
            me = _validate_myself(email, token, site)
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = f"Atlassian rejected these credentials: {e}"
            return NextAction(kind="need_input", fields=[])
        set_env({"ATLASSIAN_EMAIL": email, f"ATLASSIAN_TOKEN_{_slug(site)}": token})
        merge_routing({connector_id: {"sites": {site: "needs_review"}}})
        if connector_id == "confluence":
            spaces = [s.strip() for s in (data.get("spaces") or "").split(",") if s.strip()]
            if spaces:
                merge_routing({"confluence": {"spaces": {s: "needs_review" for s in spaces}}})
        session.status = "success"
        session.account = me.get("emailAddress") or email
        return NextAction(kind="done", message="This also connects the other Atlassian app.")

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account
