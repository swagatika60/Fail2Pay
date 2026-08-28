from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import APIKeyMiddleware
from app.config import get_settings
from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router
from app.routes.analytics import router as analytics_router
from app.routes.whatsapp import router as whatsapp_router
from app.routes.invoices import router as invoices_router
from app.routes.case_detail import router as case_detail_router
from app.routes.simulation import router as simulation_router
from app.routes.settings import router as settings_router
from app.routes.operations import router as operations_router

app = FastAPI(title="Fail2Pay")

# Validate mandatory configuration at startup
settings = get_settings()
missing = settings.validate_startup()
if missing:
    import logging

    logging.getLogger(__name__).error(
        "Missing mandatory environment variables: %s. "
        "Copy backend/.env.example to backend/.env and fill in the values.",
        ", ".join(missing),
    )

# API key authentication (only enforced when API_KEY env var is set)
app.add_middleware(APIKeyMiddleware, api_key=settings.api_key)

# CORS for local development (frontend dev server on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include payment routes
app.include_router(payments_router)

# include webhook routes
app.include_router(webhooks_router)

# include analytics routes
app.include_router(analytics_router)

# include whatsapp routes
app.include_router(whatsapp_router)

# include invoice routes
app.include_router(invoices_router)

# include case detail routes
app.include_router(case_detail_router)

# include simulation routes
app.include_router(simulation_router)

# include settings routes
app.include_router(settings_router)

# include operations list routes
app.include_router(operations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}


# --- Static frontend (production build) ---
# Serve the built React SPA if it exists (e.g. mounted in the Docker image).
FRONTEND_DIST = "/app/frontend/dist"

if __import__("os").path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=f"{FRONTEND_DIST}/assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Serve index.html for any non-API route (client-side routing)."""
        import os

        from fastapi.responses import FileResponse

        requested = os.path.join(FRONTEND_DIST, full_path)
        if os.path.isfile(requested):
            return FileResponse(requested)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
