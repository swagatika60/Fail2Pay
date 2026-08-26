from fastapi import FastAPI

from app.routes.payments import router as payments_router

app = FastAPI(title="Fail2Pay")

# include payment routes
app.include_router(payments_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}
