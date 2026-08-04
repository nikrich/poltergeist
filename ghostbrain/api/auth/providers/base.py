"""Base authentication provider interface and data structures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ghostbrain.api.auth.session import Session


@dataclass
class NextAction:
    """Represents the next action required in an authentication flow."""

    kind: str
    auth_url: str | None = None
    verification_uri: str | None = None
    user_code: str | None = None
    fields: list[dict] | None = None
    message: str | None = None


class AuthProvider(Protocol):
    """Protocol for authentication providers."""

    pattern: str

    def start(self, connector_id: str, params: dict) -> NextAction:
        """Start an authentication flow."""
        ...

    def submit(self, connector_id: str, session: "Session", data: dict) -> NextAction:
        """Submit data to advance the authentication flow."""
        ...

    def poll(self, connector_id: str, session: "Session") -> None:
        """Poll for long-running authentication flows."""
        ...

    def account_label(self, session: "Session") -> str | None:
        """Get a display label for the authenticated account."""
        ...
