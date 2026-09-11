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
    # Registration order matters, but not the way it looks: Starlette's
    # add_middleware() inserts each new `app.middleware("http")` call at the
    # FRONT of its internal list, and build_middleware_stack() then wraps
    # that list in reverse — so the LAST-registered call ends up OUTERMOST
    # (sees the request first, the response last), not the first-registered
    # one. Concretely: install_error_handling()'s request-id middleware,
    # registered second here, is outermost; auth, registered first, is
    # nested one layer inside it, above the router.
    #
    # This doesn't break auth-before-everything-else in practice, because
    # auth short-circuits an unauthenticated request by *returning* a 401
    # JSONResponse rather than raising — so it never reaches the error
    # handler's except clause, and the request-id middleware just stamps
    # X-Request-ID on that 401 on its way back out. Verified empirically via
    # ghostbrain/api/tests/test_error_handler.py (401 + X-Request-ID for an
    # unauthenticated request, JSON 500 for the boom route once authed).
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
