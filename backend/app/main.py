from fastapi import FastAPI

app = FastAPI(title="Fail2Pay")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Fail2Pay"}
