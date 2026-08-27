from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router
from app.routes.whatsapp import router as whatsapp_router

__all__ = ["payments_router", "webhooks_router", "whatsapp_router"]
