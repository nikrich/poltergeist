"""Authentication and authorization for the Ghostbrain API."""

from ghostbrain.api.auth.middleware import make_auth_middleware

__all__ = ["make_auth_middleware"]
