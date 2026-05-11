"""Bearer token middleware for the ghostbrain read API."""
from typing import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

# Paths exempt from auth (developer introspection only; sidecar binds 127.0.0.1
# so external reach is already prevented).
_UNAUTH_PATHS = frozenset({"/openapi.json", "/docs", "/redoc"})


def make_auth_middleware(
    token: str,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Build an ASGI HTTP middleware that requires `Authorization: Bearer <token>`."""
    expected = f"Bearer {token}"

    async def auth_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _UNAUTH_PATHS:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header != expected:
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return await call_next(request)

    return auth_middleware
