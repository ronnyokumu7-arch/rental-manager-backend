from functools import lru_cache
from typing import Optional, List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Rental Manager API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    
    SECRET_KEY: str
    access_token_expire_minutes: int = 10080
    database_url: str
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
    resend_api_key: str = ""
    from_email: str = "onboarding@resend.dev"
    from_name: str = "Rental Manager"
    superadmin_password: str
    tenant_admin_password: str
    frontend_url: str = "http://localhost:3000"
    uploads_dir: str = "./uploads"
    public_url_base: str = "https://rental-manager-backend-071n.onrender.com/uploads"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
