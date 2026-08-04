import json
import os
from functools import lru_cache
from typing import List, Union

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Rental Manager API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    
    # Security & Tokens
    SECRET_KEY: str
    ENCRYPTION_KEY: str  # Dedicated 32-byte base64 key for Fernet (Encrypting DB payment secrets)
    access_token_expire_minutes: int = 15  # ✅ UPDATED: Short-lived access token (15 mins)
    refresh_token_expire_days: int = 7     # ✅ NEW: 7-day refresh token for rotation
    
    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # CORS: Can be a list of strings OR a JSON string of a list of strings
    cors_origins: Union[List[str], str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
    )
    
    # Email
    resend_api_key: str = ""
    from_email: str = "onboarding@resend.dev"
    from_name: str = "Rental Manager"
    
    # Defaults / Fallbacks (Should be overridden in .env for production)
    superadmin_password: str = "change_me_in_production"
    frontend_url: str = "http://localhost:3000"
    uploads_dir: str = "./uploads"
    public_url_base: str = "https://rental-manager-backend-live.onrender.com"
    google_maps_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # ✅ Ignores unknown env vars to prevent crashes during deployment
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str], None]) -> List[str]:
        """
        Robustly parses CORS origins from the environment variable.
        Handles both JSON arrays and comma-separated strings.
        """
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                # It's a JSON string
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if origin.strip()]
                except json.JSONDecodeError:
                    pass
            
            # Fallback: It's a comma-separated string
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        
        if isinstance(v, list):
            return [str(origin).strip() for origin in v if origin]
            
        # Ultimate fallback
        return ["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of Settings.
    This ensures the .env file is only read once per application lifecycle,
    improving performance and preventing memory leaks.
    """
    return Settings()
