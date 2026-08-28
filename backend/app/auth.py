"""API Key Authentication Middleware.

Secures private API endpoints with Bearer token authentication.
Public routes (webhooks, health, customer-facing invoice access) are exempt.

Auth is only enforced when the API_KEY environment variable is set.
When unset, all requests are allowed through (development/test mode).

Usage:
    Set API_KEY in your environment or .env file to enable authentication.
    Clients must send: Authorization: Bearer <your-api-key>
"""

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Routes that are always public (no API key required).
# Webhooks verify their own signatures; health is for liveness probes;
# invoice access/download links are shared with customers via secure tokens.
PUBLIC_PATHS: set[str] = {
    "/health",
    "/api/health",
    "/api/webhooks/razorpay",
    "/api/webhooks/whatsapp",
}

# Prefixes that are always public (matched by startswith).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/invoices/access/",
    "/api/invoices/download/",
)


def _is_public(path: str) -> bool:
    """Return True if the path is exempt from authentication."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(pfx) for pfx in PUBLIC_PREFIXES)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Bearer token auth on protected routes.

    If ``api_key`` is empty or ``None``, authentication is disabled
    (development / test mode).
    """

    def __init__(self, app, api_key: str = ""):
        super().__init__(app)
        self.api_key = api_key.strip()

    async def dispatch(self, request: Request, call_next: Callable):
        # Auth disabled — pass through
        if not self.api_key:
            return await call_next(request)

        path = request.url.path

        # Public routes — pass through
        if _is_public(path):
            return await call_next(request)

        # Validate Authorization header
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing API key: %s %s", request.method, path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key. Send Authorization: Bearer <key>"},
            )

        token = auth_header[7:]  # strip "Bearer "
        if token != self.api_key:
            logger.warning("Invalid API key: %s %s", request.method, path)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key"},
            )

        return await call_next(request)
