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
    app_name: str = "Rental Garage API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    
    # ─────────────────────────────────────────────────────────────────────────
    # SECURITY & TOKENS (REQUIRED - Set in Render Dashboard)
    # ─────────────────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=32)  # ✅ Required, min 32 chars
    ENCRYPTION_KEY: str = Field(..., min_length=44)  # ✅ Required, 32-byte base64 = 44 chars
    access_token_expire_minutes: int = 60
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
    from_name: str = "Rental Garage"
    
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

    # ✅ NEW: RENDER DEPLOYMENT FIX
    @field_validator("database_url", mode="after")
    @classmethod
    def enforce_asyncpg_driver(cls, v: str) -> str:
        """
        Render provides bare 'postgresql://' URLs which default to the missing psycopg2.
        We force it to use 'postgresql+asyncpg://' for the main async app.
        Alembic's env.py will then safely swap '+asyncpg' to '+psycopg' for sync migrations.
        """
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
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
def get_settings(_env_file: str | None = ".env") -> Settings:
    """
    Returns a cached instance of Settings.
    """
    return Settings(_env_file=_env_file)
