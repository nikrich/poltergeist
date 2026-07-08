"""FastAPI app factory for the ghostbrain read API."""
from fastapi import FastAPI

from ghostbrain.api.auth import make_auth_middleware
from ghostbrain.api.routes import activity as activity_routes
from ghostbrain.api.routes import agenda as agenda_routes
from ghostbrain.api.routes import answer as answer_routes
from ghostbrain.api.routes import chat as chat_routes
from ghostbrain.api.routes import mcp_servers as mcp_servers_routes
from ghostbrain.api.routes import captures as captures_routes
from ghostbrain.api.routes import connectors as connectors_routes
from ghostbrain.api.routes import daily as daily_routes
from ghostbrain.api.routes import docs as docs_routes
from ghostbrain.api.routes import import_atlassian as import_routes
from ghostbrain.api.routes import notes as notes_routes
from ghostbrain.api.routes import recorder as recorder_routes
from ghostbrain.api.routes import scheduler as scheduler_routes
from ghostbrain.api.routes import search as search_routes
from ghostbrain.api.routes import settings as settings_routes
from ghostbrain.api.routes import meetings as meetings_routes
from ghostbrain.api.routes import projects as projects_routes
from ghostbrain.api.routes import suggestions as suggestions_routes
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
    app.include_router(daily_routes.router)
    app.include_router(docs_routes.router)
    app.include_router(import_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(recorder_routes.router)
    app.include_router(scheduler_routes.router)
    app.include_router(search_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(activity_routes.router)
    app.include_router(answer_routes.router)
    app.include_router(mcp_servers_routes.router)  # before chat: its /v1/chat/{id} catch-all
    app.include_router(chat_routes.router)
    app.include_router(suggestions_routes.router)
    app.include_router(projects_routes.router)
    return app
