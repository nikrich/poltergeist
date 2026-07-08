from __future__ import annotations

import logging

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import merge_routing

log = logging.getLogger("ghostbrain.api.auth.providers.paste_token")


def _slack_auth_test(token: str) -> dict:
    from slack_sdk import WebClient

    return WebClient(token=token).auth_test().data


def _joplin_ping(host: str, token: str) -> bool:
    import requests

    r = requests.get(f"{host.rstrip('/')}/ping", params={"token": token}, timeout=10)
    return r.status_code == 200 and r.text.strip() == "JoplinClipperServer"


class SlackTokenProvider:
    pattern = "paste_token"

    def start(self, connector_id, params):
        return NextAction(
            kind="need_input",
            message="Create a Slack app, add the User Token scopes, install it, and paste the xoxp- token.",
            fields=[
                {"name": "workspace_slug", "label": "Workspace slug", "type": "text",
                 "placeholder": "work"},
                {"name": "token", "label": "User OAuth Token", "type": "password",
                 "placeholder": "xoxp-…"},
            ],
        )

    def submit(self, connector_id, session, data):
        from ghostbrain.connectors.slack.auth import SlackAuthError, save_token

        slug = (data.get("workspace_slug") or "").strip()
        token = (data.get("token") or "").strip()
        if not slug:
            session.status = "error"; session.error = "Workspace slug is required"
            return NextAction(kind="need_input", fields=[])
        if not token.startswith(("xoxp-", "xoxb-")):
            session.status = "error"
            session.error = "Token must start with xoxp- (User OAuth) or xoxb- (Bot)."
            return NextAction(kind="need_input", fields=[])
        try:
            ident = _slack_auth_test(token)  # network validate, no persist yet
        except Exception as e:  # noqa: BLE001
            session.status = "error"; session.error = f"Slack rejected the token: {e}"
            return NextAction(kind="need_input", fields=[])
        try:
            save_token(slug, token)  # only persist after a successful auth.test
        except SlackAuthError as e:
            session.status = "error"; session.error = str(e)
            return NextAction(kind="need_input", fields=[])
        session.status = "success"
        session.account = f"@{ident.get('user')} · {ident.get('team')}"
        merge_routing({"slack": {"workspaces": {slug: {"context": "needs_review",
                       "lookback_hours": 24, "mentions_only": True}}}})
        return NextAction(kind="done")

    def poll(self, connector_id, session):  # not used
        pass

    def account_label(self, session):
        return session.account


class JoplinTokenProvider:
    pattern = "paste_token"

    def start(self, connector_id, params):
        return NextAction(
            kind="need_input",
            message="In Joplin: Tools → Options → Web Clipper → enable the service, then copy the token.",
            fields=[
                {"name": "token", "label": "Web Clipper token", "type": "password"},
                {"name": "host", "label": "Host (optional)", "type": "text",
                 "placeholder": "http://localhost:41184"},
            ],
        )

    def submit(self, connector_id, session, data):
        token = (data.get("token") or "").strip()
        host = (data.get("host") or "http://localhost:41184").strip()
        if not token:
            session.status = "error"; session.error = "Token is required"
            return NextAction(kind="need_input", fields=[])
        try:
            ok = _joplin_ping(host, token)
        except Exception as e:  # noqa: BLE001
            # _joplin_ping sends the token as a URL query param, so the
            # exception string from a failed request may contain it
            # (e.g. connection errors echo the full URL). Never put `e`
            # into session.error — log it server-side instead.
            log.warning("Joplin ping failed for host %s: %s", host, e)
            session.status = "error"
            session.error = (
                "Could not reach Joplin — check the host and that the "
                "Web Clipper service is running."
            )
            return NextAction(kind="need_input", fields=[])
        if not ok:
            session.status = "error"; session.error = "Joplin rejected the token or Web Clipper is off"
            return NextAction(kind="need_input", fields=[])
        session.status = "success"; session.account = host
        merge_routing({"joplin": {"token": token, "host": host}})
        return NextAction(kind="done")

    def poll(self, connector_id, session):
        pass

    def account_label(self, session):
        return session.account
