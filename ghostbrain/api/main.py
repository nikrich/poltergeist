"""FastAPI app factory for the ghostbrain read API."""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ghostbrain.api.auth import make_auth_middleware
from ghostbrain.api.routes import activity as activity_routes
from ghostbrain.api.routes import agenda as agenda_routes
from ghostbrain.api.routes import answer as answer_routes
from ghostbrain.api.routes import captures as captures_routes
from ghostbrain.api.routes import chat as chat_routes
from ghostbrain.api.routes import connector_auth as connector_auth_routes
from ghostbrain.api.routes import connectors as connectors_routes
from ghostbrain.api.routes import daily as daily_routes
from ghostbrain.api.routes import docs as docs_routes
from ghostbrain.api.routes import doctor as doctor_routes
from ghostbrain.api.routes import health as health_routes
from ghostbrain.api.routes import import_atlassian as import_routes
from ghostbrain.api.routes import llm as llm_routes
from ghostbrain.api.routes import mcp_servers as mcp_servers_routes
from ghostbrain.api.routes import meetings as meetings_routes
from ghostbrain.api.routes import notes as notes_routes
from ghostbrain.api.routes import projects as projects_routes
from ghostbrain.api.routes import recorder as recorder_routes
from ghostbrain.api.routes import scheduler as scheduler_routes
from ghostbrain.api.routes import search as search_routes
from ghostbrain.api.routes import settings as settings_routes
from ghostbrain.api.routes import suggestions as suggestions_routes
from ghostbrain.api.routes import vault as vault_routes

API_VERSION = "1.0.0"

log = logging.getLogger("ghostbrain.api")


def install_error_handling(app: FastAPI) -> None:
    """Request ids + a traceback in the log for every unhandled exception.

    Without this, Starlette's traceback goes to uvicorn's stderr logger, which
    never propagates to the file handler — the 500 that broke the recorder for
    a first-run user left no line in sidecar.log at all.
    """

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:  # logged with traceback below, then reported as a 500
            log.exception("unhandled error request_id=%s %s %s", rid, request.method, request.url.path)
            response = JSONResponse({"detail": "Internal error", "requestId": rid}, status_code=500)
        response.headers["X-Request-ID"] = rid
        return response


def create_app(token: str) -> FastAPI:
    """Build a FastAPI app with auth + all routers wired."""
    app = FastAPI(
        title="ghostbrain",
        description="Read-only API for the ghostbrain desktop app.",
        version=API_VERSION,
    )
    # Registration order matters: Starlette wraps middleware so the
    # FIRST-registered `app.middleware("http")` call ends up OUTERMOST (it
    # sees the request before anything else and the response after
    # everything else), and each later registration nests one layer closer
    # to the route. Auth must run first (outermost) so an unauthenticated
    # request short-circuits with 401 before the route or the error handler
    # ever sees it, so it is registered before install_error_handling here.
    # The error handler still needs to be able to catch exceptions raised by
    # route code, which it can from its position between auth and the
    # router. Verified empirically via ghostbrain/api/tests/test_error_handler.py
    # (401 for unauthenticated + JSON 500 for the boom route).
    app.middleware("http")(make_auth_middleware(token))
    install_error_handling(app)
    app.include_router(health_routes.router)
    app.include_router(vault_routes.router)
    app.include_router(connectors_routes.router)
    app.include_router(captures_routes.router)
    app.include_router(meetings_routes.router)
    app.include_router(agenda_routes.router)
    app.include_router(daily_routes.router)
    app.include_router(docs_routes.router)
    app.include_router(import_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(recorder_routes.router)
    app.include_router(scheduler_routes.router)
    app.include_router(doctor_routes.router)
    app.include_router(search_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(activity_routes.router)
    app.include_router(answer_routes.router)
    app.include_router(mcp_servers_routes.router)  # before chat: its /v1/chat/{id} catch-all
    app.include_router(chat_routes.router)
    app.include_router(llm_routes.router)
    app.include_router(suggestions_routes.router)
    app.include_router(projects_routes.router)
    app.include_router(connector_auth_routes.router)
    import ghostbrain.api.auth.providers.register_all  # noqa: F401  (registers providers, Task D6)
    return app
