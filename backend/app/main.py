from fastapi import FastAPI

from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router
from app.routes.analytics import router as analytics_router
from app.routes.whatsapp import router as whatsapp_router

app = FastAPI(title="Fail2Pay")

# include payment routes
app.include_router(payments_router)

# include webhook routes
app.include_router(webhooks_router)

# include analytics routes
app.include_router(analytics_router)

# include whatsapp routes
app.include_router(whatsapp_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}
