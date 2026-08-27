from fastapi import FastAPI

from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router

app = FastAPI(title="Fail2Pay")

# include payment routes
app.include_router(payments_router)

# include webhook routes
app.include_router(webhooks_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}
