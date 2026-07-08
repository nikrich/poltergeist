from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.repo.routing import load_routing, merge_routing


def _app_config() -> dict:
    return (load_routing().get("microsoft") or {})


def _has_app_config() -> bool:
    import os

    cfg = _app_config()
    cid = cfg.get("client_id") or os.environ.get("MS_GRAPH_CLIENT_ID")
    tid = cfg.get("tenant_id") or os.environ.get("MS_GRAPH_TENANT_ID")
    return bool(cid and tid)


def _build_app(cfg: dict):
    # Reuse the existing token-cache + PublicClientApplication builder.
    from ghostbrain.connectors.microsoft.graph.auth import _build_app as build

    return build(cfg)


def _scopes(cfg: dict) -> list[str]:
    from ghostbrain.connectors.microsoft.graph.auth import resolve_scopes

    return resolve_scopes(cfg)


class MicrosoftProvider:
    pattern = "ms_device_code"

    def _app_config_fields(self) -> NextAction:
        return NextAction(
            kind="need_input",
            message="Register a public-client Azure app (device-code, no secret), then enter its IDs.",
            fields=[
                {"name": "client_id", "label": "Application (client) ID", "type": "text"},
                {"name": "tenant_id", "label": "Directory (tenant) ID", "type": "text"},
            ],
        )

    def start(self, connector_id, params):
        if not _has_app_config():
            return self._app_config_fields()
        return self._begin_device_flow(_app_config())

    def _begin_device_flow(self, cfg: dict) -> NextAction:
        app = _build_app(cfg)
        flow = app.initiate_device_flow(scopes=_scopes(cfg))
        if "user_code" not in flow:
            return NextAction(kind="need_input", message=f"Could not start device flow: {flow}", fields=[])
        # stash flow on the session via the returned action's message-free fields:
        self._pending_flow = flow  # picked up by poll through session (see submit/start wiring)
        return NextAction(
            kind="show_device_code",
            verification_uri=flow.get("verification_uri"),
            user_code=flow.get("user_code"),
            message=flow.get("message"),
        )

    def submit(self, connector_id, session, data):
        cid = (data.get("client_id") or "").strip()
        tid = (data.get("tenant_id") or "").strip()
        if not (cid and tid):
            session.status = "error"; session.error = "client_id and tenant_id are required"
            return NextAction(kind="need_input", fields=[])
        merge_routing({"microsoft": {"client_id": cid, "tenant_id": tid}})
        action = self._begin_device_flow(_app_config())
        session.next = action
        if action.kind == "show_device_code":
            session.status = "pending"
            session._ms_flow = self._pending_flow  # type: ignore[attr-defined]
        return action

    def poll(self, connector_id, session):
        # Narrow the shared-instance handoff window: whichever flow was stashed
        # (session._ms_flow from submit(), or self._pending_flow from a
        # start()-goes-straight-to-device-code path) is copied onto the
        # session up front, so the rest of poll() has a single, consistent
        # source of truth even if self._pending_flow changes afterwards.
        if getattr(session, "_ms_flow", None) is None:
            session._ms_flow = getattr(self, "_pending_flow", None)  # type: ignore[attr-defined]
        flow = session._ms_flow  # type: ignore[attr-defined]
        if flow is None:
            session.status = "error"; session.error = "No device flow in progress"
            return
        cfg = _app_config()
        app = _build_app(cfg)
        result = app.acquire_token_by_device_flow(flow)  # blocks until done/expired
        if "access_token" not in result:
            session.status = "error"
            session.error = result.get("error_description", "Microsoft sign-in failed")
            return
        accounts = app.get_accounts()
        session.account = accounts[0].get("username") if accounts else "your account"
        session.status = "success"
        session.next = NextAction(kind="done")

    def account_label(self, session):
        return session.account
