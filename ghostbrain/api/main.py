"""FastAPI app factory for the ghostbrain read API."""
from fastapi import FastAPI

from ghostbrain.api.auth import make_auth_middleware
from ghostbrain.api.routes import activity as activity_routes
from ghostbrain.api.routes import agenda as agenda_routes
from ghostbrain.api.routes import captures as captures_routes
from ghostbrain.api.routes import connectors as connectors_routes
from ghostbrain.api.routes import meetings as meetings_routes
from ghostbrain.api.routes import vault as vault_routes

API_VERSION = "1.0.0"


def create_app(token: str) -> FastAPI:
    """Build a FastAPI app with auth + all routers wired."""
    app = FastAPI(
        title="ghostbrain",
        description="Read-only API for the ghostbrain desktop app.",
        version=API_VERSION,
    )
    app.middleware("http")(make_auth_middleware(token))
    app.include_router(vault_routes.router)
    app.include_router(connectors_routes.router)
    app.include_router(captures_routes.router)
    app.include_router(meetings_routes.router)
    app.include_router(agenda_routes.router)
    app.include_router(activity_routes.router)
    return app
