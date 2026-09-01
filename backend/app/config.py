from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    # API Authentication
    api_key: str = ""
    # AI Intent Detection settings
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: int = 5  # Reduced from 10s for faster conversational responses
    ai_confidence_threshold: float = 0.6
    # WhatsApp settings
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    email_api_key: str = ""
    email_from_address: str = "noreply@fail2pay.com"
    # Email delivery provider. "resend" uses the Resend REST API; "mock" (or an
    # empty email_api_key) logs emails without delivering them. The endpoint and
    # sender/recipient are configurable via EMAIL_PROVIDER_URL / EMAIL_FROM_NAME.
    email_provider: str = "resend"
    email_provider_url: str = "https://api.resend.com/emails"
    email_from_name: str = "Fail2Pay"
    payment_link_base_url: str = "https://fail2pay.example.com"
    # Public payment portal host where the React SPA is served. This is where
    # the clickable customer payment link resolves (e.g. http://localhost:5173
    # in local dev, or https://pay.fail2pay.com in prod). The base URL setting
    # is used as a fallback when the portal host is not explicitly configured.
    payment_portal_base_url: str = "http://localhost:5173"
    promise_high_value_threshold_paise: int = 1_000_000  # ₹10,000
    # Cost of recovery (per outreach message, in paise). Used to compute the
    # cost-of-recovery ratio against verified recovered revenue. These are
    # accounting constants with sane defaults — no per-case storage needed.
    recovery_cost_per_whatsapp_paise: int = 40  # ₹0.40 per delivered WA message
    recovery_cost_per_email_paise: int = 10  # ₹0.10 per emailed invoice/reminder

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_startup(self) -> list[str]:
        """Check mandatory keys and return list of missing ones.

        Called at startup to fail fast with a clear message.
        """
        missing = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if not self.razorpay_key_id:
            missing.append("RAZORPAY_KEY_ID")
        if not self.razorpay_key_secret:
            missing.append("RAZORPAY_KEY_SECRET")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
