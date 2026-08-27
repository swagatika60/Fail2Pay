from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
