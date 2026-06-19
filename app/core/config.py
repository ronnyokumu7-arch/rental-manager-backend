from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Rental Manager API"
    environment: str = "development"
    debug: bool = False
    SECRET_KEY: str = "your-secret-key-change-in-env"
    access_token_expire_minutes: int = 60
    database_url: str = "postgresql://postgres:rentalpass@localhost:5432/rental_manager"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
    resend_api_key: str = ""
    from_email: str = "onboarding@resend.dev"
    from_name: str = "Rental Manager"
    superadmin_password: str = "changeme"
    tenant_admin_password: str = "changeme"
    frontend_url: str = "http://localhost:3002"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
