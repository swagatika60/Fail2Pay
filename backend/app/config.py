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
    ai_timeout_seconds: int = 10
    ai_confidence_threshold: float = 0.6
    # WhatsApp settings
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    email_api_key: str = ""
    email_from_address: str = "noreply@fail2pay.com"
    payment_link_base_url: str = "https://fail2pay.example.com"
    promise_high_value_threshold_paise: int = 1_000_000  # ₹10,000

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
