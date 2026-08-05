import json
import os
from functools import lru_cache
from typing import List, Union, Optional

from pydantic import field_validator, Field, HttpUrl, AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ─────────────────────────────────────────────────────────────────────────
    # APP IDENTIFICATION
    # ─────────────────────────────────────────────────────────────────────────
    app_name: str = "Rental Manager API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    
    # ─────────────────────────────────────────────────────────────────────────
    # SECURITY & TOKENS (REQUIRED - Set in Render Dashboard)
    # ─────────────────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=32)  # ✅ Required, min 32 chars
    ENCRYPTION_KEY: str = Field(..., min_length=44)  # ✅ Required, 32-byte base64 = 44 chars
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    
    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE (REQUIRED - Set in Render Dashboard)
    # ─────────────────────────────────────────────────────────────────────────
    database_url: str = Field(..., min_length=10)  # ✅ Required, basic length check
    
    # ─────────────────────────────────────────────────────────────────────────
    # REDIS (Optional - defaults to local for development)
    # ─────────────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    
    # ─────────────────────────────────────────────────────────────────────────
    # CORS: Can be a list of strings OR a JSON string of a list of strings
    # ─────────────────────────────────────────────────────────────────────────
    cors_origins: Union[List[str], str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
    )
    
    # ─────────────────────────────────────────────────────────────────────────
    # EMAIL (Optional - defaults allow local testing)
    # ─────────────────────────────────────────────────────────────────────────
    resend_api_key: str = ""
    from_email: str = "onboarding@resend.dev"
    from_name: str = "Rental Manager"
    
    # ─────────────────────────────────────────────────────────────────────────
    # URLS & PATHS (Optional - defaults for local dev)
    # ─────────────────────────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"
    public_url_base: str = "https://rental-manager-backend-live.onrender.com"
    uploads_dir: str = "./uploads"
    google_maps_api_key: str = ""
    
    # ─────────────────────────────────────────────────────────────────────────
    # ⚠️ SUPERADMIN PASSWORD - NO DEFAULT! Must be set in production.
    # ─────────────────────────────────────────────────────────────────────────
    superadmin_password: Optional[str] = None  # ✅ No fallback value
    
    # ─────────────────────────────────────────────────────────────────────────
    # PYDANTIC CONFIG
    # ─────────────────────────────────────────────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # ✅ Ignores unknown env vars to prevent crashes during deployment
    )

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATORS
    # ─────────────────────────────────────────────────────────────────────────
    
    @field_validator("database_url", "redis_url", "frontend_url", "public_url_base", mode="before")
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Ensure URL fields are properly formatted strings."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"URL field must be a non-empty string, got: {type(v)}")
        return v.strip()
    
    @field_validator("SECRET_KEY", "ENCRYPTION_KEY")
    @classmethod
    def validate_secrets(cls, v: str) -> str:
        """Ensure secrets are not empty and meet minimum length requirements."""
        if not v or len(v.strip()) < 32:
            raise ValueError("SECRET_KEY and ENCRYPTION_KEY must be at least 32 characters")
        return v.strip()
    
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
    
    @field_validator("debug", mode="before")
    @classmethod
    def auto_debug_for_dev(cls, v: Optional[bool], info) -> bool:
        """Auto-enable debug mode in development environment if not explicitly set."""
        if v is not None:
            return bool(v)
        # Check the already-parsed environment field
        env = info.data.get("environment", "development")
        return env.lower() in ("development", "dev", "local")


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of Settings.
    This ensures the .env file is only read once per application lifecycle,
    improving performance and preventing memory leaks.
    
    ⚠️ In production (Render), all required fields must be set as Environment Variables
    in the Render Dashboard:
      - SECRET_KEY (min 32 chars, use: python -c "import secrets; print(secrets.token_urlsafe(32))")
      - ENCRYPTION_KEY (44-char base64, use: python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
      - DATABASE_URL (from Render PostgreSQL "Internal Database URL", prefix with postgresql+asyncpg://)
      - superadmin_password (set a strong, unique password)
    """
    return Settings()
