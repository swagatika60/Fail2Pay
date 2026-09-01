import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import APIKeyMiddleware
from app.config import get_settings
from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router
from app.routes.analytics import router as analytics_router
from app.routes.whatsapp import router as whatsapp_router
from app.routes.whatsapp import webhook_router as whatsapp_cloud_router
from app.routes.invoices import router as invoices_router
from app.routes.case_detail import router as case_detail_router
from app.routes.simulation import router as simulation_router
from app.routes.settings import router as settings_router
from app.routes.operations import router as operations_router
from app.routes.realtime import router as realtime_router
from app.routes.triggers import router as triggers_router
from app.routes.receivables import router as receivables_router
from app.routes.voice import router as voice_router
from app.routes.subscription_checkout import router as sub_checkout_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optionally run the autonomous recovery scheduler loop in the background.

    The loop is OFF by default and only starts when the ``ENABLE_AUTONOMOUS_SCHEDULER``
    environment variable is set to ``1``. It polls for due scheduled actions and runs
    the full guardrail pipeline (terminal states, opt-out, dispute, max attempts,
    recovered payment) on an interval. Gated so test clients never start it.
    """
    # Capture the main event loop so sync (threadpool) route handlers — the
    # simulate-message demo driver, webhook processing — can still push live
    # WebSocket broadcasts instead of silently dropping them.
    from app.services.realtime import bind_main_loop

    bind_main_loop(asyncio.get_running_loop())

    stop_event = asyncio.Event()
    task = None
    if os.getenv("ENABLE_AUTONOMOUS_SCHEDULER") == "1":
        from app.services import scheduler

        task = asyncio.create_task(
            scheduler.run_scheduler_loop(
                poll_interval=scheduler.SCHEDULER_POLL_INTERVAL_SECONDS,
                stop_event=stop_event,
            )
        )
        logging.getLogger(__name__).info("Autonomous recovery scheduler loop started")
    try:
        yield
    finally:
        if task is not None:
            stop_event.set()
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass


app = FastAPI(title="Fail2Pay", lifespan=lifespan)

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
app.include_router(whatsapp_cloud_router)

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

# include realtime websocket routes
app.include_router(realtime_router)

# include external revenue-trigger routes
app.include_router(triggers_router)

# include B2B receivables chaser routes
app.include_router(receivables_router)

# include voice recovery routes
app.include_router(voice_router)

# include checkout & subscription list routes
app.include_router(sub_checkout_router)


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
