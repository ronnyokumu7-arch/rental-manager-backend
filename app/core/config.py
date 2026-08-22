import json
import os
import warnings
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
    access_token_expire_minutes: int = 15  # ✅ Reduced from 60 for better security
    refresh_token_expire_days: int = 7
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 RATE LIMITING CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    # Login endpoint: strict to prevent brute force
    login_rate_limit: int = 5  # Max attempts per window
    login_rate_window: int = 60  # Window in seconds (1 minute)
    
    # Password reset: very strict to prevent enumeration
    password_reset_rate_limit: int = 3  # Max attempts per window
    password_reset_rate_window: int = 60  # Window in seconds
    
    # General API endpoints: more lenient
    api_rate_limit: int = 100  # Max requests per window
    api_rate_window: int = 60  # Window in seconds
    
    # File upload endpoints: moderate to prevent abuse
    upload_rate_limit: int = 20  # Max uploads per window
    upload_rate_window: int = 60  # Window in seconds
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 ACCOUNT LOCKOUT CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    # Lock account after N failed attempts
    max_failed_login_attempts: int = 5
    # Lock duration in minutes
    account_lockout_duration_minutes: int = 15
    # Window to count failed attempts (in seconds)
    failed_attempts_window_seconds: int = 3600  # 1 hour
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 SECURITY LOGGING CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    # Log level for security events (DEBUG, INFO, WARNING, ERROR)
    security_log_level: str = "INFO"
    # Enable detailed security audit logging
    enable_security_audit: bool = True
    # Log failed authentication attempts
    log_failed_auth_attempts: bool = True
    # Log rate limit violations
    log_rate_limit_violations: bool = True
    # Log account lockouts
    log_account_lockouts: bool = True
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 PASSWORD POLICY
    # ─────────────────────────────────────────────────────────────────────────
    # Minimum password length (enforced at validation layer)
    min_password_length: int = 8
    # Maximum password length (bcrypt limit is 72 bytes)
    max_password_length: int = 72
    # Require at least one uppercase letter
    require_uppercase: bool = True
    # Require at least one lowercase letter
    require_lowercase: bool = True
    # Require at least one number
    require_number: bool = True
    # Require at least one special character
    require_special_char: bool = False  # Can enable for stricter policy
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 SESSION SECURITY
    # ─────────────────────────────────────────────────────────────────────────
    # Force logout on password change
    logout_on_password_change: bool = True
    # Maximum concurrent sessions per user (0 = unlimited)
    max_concurrent_sessions: int = 5
    # Session timeout in minutes (0 = use token expiry)
    session_timeout_minutes: int = 0
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 CORS SECURITY
    # ─────────────────────────────────────────────────────────────────────────
    cors_origins: Union[List[str], str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
    )
    # Allow credentials in CORS requests
    cors_allow_credentials: bool = True
    # CORS max age in seconds (how long preflight can be cached)
    cors_max_age: int = 3600
    
    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE (REQUIRED - Set in Render Dashboard)
    # ─────────────────────────────────────────────────────────────────────────
    database_url: str = Field(..., min_length=10)  # ✅ Required, basic length check
    
    # ─────────────────────────────────────────────────────────────────────────
    # REDIS (Optional - defaults to local for development)
    # ─────────────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    
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
    # STORAGE BACKEND (Cloudinary or local disk)
    # Switch via env var: STORAGE_BACKEND=cloudinary | local (default)
    # Local uses `uploads_dir` above. Cloudinary uses the 3 creds below.
    # All stored URLs in the DB stays identical across backends.
    # ─────────────────────────────────────────────────────────────────────────
    storage_backend: str = "local"          # "local" | "cloudinary"
    cloudinary_cloud_name: str = ""         # e.g. "gbua3kjg"
    cloudinary_api_key: str = ""            # numeric, from Cloudinary dashboard
    cloudinary_api_secret: str = ""         # from Cloudinary dashboard
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 FILE UPLOAD SECURITY
    # ─────────────────────────────────────────────────────────────────────────
    # Maximum file size in bytes (default: 10MB)
    max_upload_size: int = 10 * 1024 * 1024
    # Allowed file extensions for uploads
    allowed_file_extensions: List[str] = [
        ".jpg", ".jpeg", ".png", ".gif", ".webp",  # Images
        ".pdf",  # Documents
        ".doc", ".docx",  # Word
        ".xls", ".xlsx",  # Excel
    ]
    # Allowed MIME types for uploads
    allowed_mime_types: List[str] = [
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 SECURITY HEADERS
    # ─────────────────────────────────────────────────────────────────────────
    # Enable HSTS (HTTP Strict Transport Security)
    enable_hsts: bool = True
    # HSTS max age in seconds (default: 1 year)
    hsts_max_age: int = 31536000
    # Include subdomains in HSTS
    hsts_include_subdomains: bool = True
    # Enable HSTS preload (requires submission to preload list)
    hsts_preload: bool = False
    
    # ─────────────────────────────────────────────────────────────────────────
    # 🔒 BRUTE FORCE PROTECTION
    # ─────────────────────────────────────────────────────────────────────────
    # Enable IP-based rate limiting
    enable_ip_rate_limiting: bool = True
    # Enable account-based lockout
    enable_account_lockout: bool = True
    # Enable CAPTCHA after N failed attempts
    enable_captcha_after_failures: bool = False
    captcha_threshold: int = 3  # Show CAPTCHA after this many failures
    
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

    # ✅ RENDER DEPLOYMENT FIX
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

    # ✅ STORAGE BACKEND VALIDATOR (graceful, never crashes)
    @field_validator("storage_backend", "cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret")
    @classmethod
    def normalize_storage(cls, v: Optional[str]) -> str:
        """Strip whitespace; empty becomes '' so downstream checks are trivial."""
        if v is None:
            return ""
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
    
    # ✅ SECURITY VALIDATORS
    @field_validator("security_log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure security log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper
    
    @field_validator("max_upload_size")
    @classmethod
    def validate_upload_size(cls, v: int) -> int:
        """Ensure upload size is reasonable (1MB to 100MB)."""
        if v < 1024 * 1024:  # Less than 1MB
            warnings.warn("max_upload_size is very small (< 1MB)")
        if v > 100 * 1024 * 1024:  # More than 100MB
            warnings.warn("max_upload_size is very large (> 100MB), consider reducing")
        return v
    
    @field_validator("allowed_file_extensions")
    @classmethod
    def validate_file_extensions(cls, v: List[str]) -> List[str]:
        """Ensure file extensions are properly formatted."""
        return [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in v]
    
    @field_validator("login_rate_limit", "password_reset_rate_limit", "api_rate_limit", "upload_rate_limit")
    @classmethod
    def validate_rate_limits(cls, v: int, info) -> int:
        """Ensure rate limits are reasonable."""
        if v < 1:
            raise ValueError(f"{info.field_name} must be at least 1")
        if v > 1000:
            warnings.warn(f"{info.field_name} is very high (> 1000), may not provide adequate protection")
        return v
    
    @field_validator("max_failed_login_attempts")
    @classmethod
    def validate_lockout_attempts(cls, v: int) -> int:
        """Ensure lockout threshold is reasonable."""
        if v < 3:
            warnings.warn("max_failed_login_attempts is very low (< 3), may cause user frustration")
        if v > 10:
            warnings.warn("max_failed_login_attempts is high (> 10), may not prevent brute force")
        return v
    
    @field_validator("account_lockout_duration_minutes")
    @classmethod
    def validate_lockout_duration(cls, v: int) -> int:
        """Ensure lockout duration is reasonable."""
        if v < 1:
            raise ValueError("account_lockout_duration_minutes must be at least 1")
        if v > 1440:  # More than 24 hours
            warnings.warn("account_lockout_duration_minutes is very long (> 24 hours)")
        return v
    
    @field_validator("access_token_expire_minutes")
    @classmethod
    def validate_access_token_expiry(cls, v: int) -> int:
        """Ensure access token expiry is reasonable."""
        if v < 5:
            warnings.warn("access_token_expire_minutes is very short (< 5 min), may cause UX issues")
        if v > 1440:  # More than 24 hours
            warnings.warn("access_token_expire_minutes is very long (> 24 hours), security risk")
        return v
    
    @field_validator("refresh_token_expire_days")
    @classmethod
    def validate_refresh_token_expiry(cls, v: int) -> int:
        """Ensure refresh token expiry is reasonable."""
        if v < 1:
            raise ValueError("refresh_token_expire_days must be at least 1")
        if v > 365:  # More than 1 year
            warnings.warn("refresh_token_expire_days is very long (> 1 year), security risk")
        return v
    
    @field_validator("min_password_length")
    @classmethod
    def validate_min_password_length(cls, v: int) -> int:
        """Ensure minimum password length is secure."""
        if v < 8:
            warnings.warn("min_password_length is less than 8, consider increasing for security")
        return v
    
    @field_validator("max_concurrent_sessions")
    @classmethod
    def validate_max_sessions(cls, v: int) -> int:
        """Ensure max sessions is reasonable."""
        if v < 0:
            raise ValueError("max_concurrent_sessions cannot be negative")
        return v


@lru_cache
def get_settings(_env_file: str | None = ".env") -> Settings:
    """
    Returns a cached instance of Settings.
    """
    return Settings(_env_file=_env_file)


# ─────────────────────────────────────────────────────────────────────────
# ✅ CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────

def is_production() -> bool:
    """Check if running in production environment."""
    settings = get_settings()
    return settings.environment.lower() in ("production", "prod")


def is_development() -> bool:
    """Check if running in development environment."""
    settings = get_settings()
    return settings.environment.lower() in ("development", "dev", "local")


def is_testing() -> bool:
    """Check if running in testing environment."""
    settings = get_settings()
    return settings.environment.lower() in ("testing", "test")


def get_security_config_summary() -> dict:
    """
    Returns a summary of security configuration for debugging/logging.
    Does NOT include sensitive values like SECRET_KEY or ENCRYPTION_KEY.
    """
    settings = get_settings()
    return {
        "environment": settings.environment,
        "debug": settings.debug,
        "rate_limiting": {
            "login": {
                "limit": settings.login_rate_limit,
                "window_seconds": settings.login_rate_window,
            },
            "password_reset": {
                "limit": settings.password_reset_rate_limit,
                "window_seconds": settings.password_reset_rate_window,
            },
            "api": {
                "limit": settings.api_rate_limit,
                "window_seconds": settings.api_rate_window,
            },
            "upload": {
                "limit": settings.upload_rate_limit,
                "window_seconds": settings.upload_rate_window,
            },
        },
        "account_lockout": {
            "enabled": settings.enable_account_lockout,
            "max_attempts": settings.max_failed_login_attempts,
            "duration_minutes": settings.account_lockout_duration_minutes,
            "window_seconds": settings.failed_attempts_window_seconds,
        },
        "security_logging": {
            "enabled": settings.enable_security_audit,
            "log_level": settings.security_log_level,
            "log_failed_auth": settings.log_failed_auth_attempts,
            "log_rate_violations": settings.log_rate_limit_violations,
            "log_lockouts": settings.log_account_lockouts,
        },
        "password_policy": {
            "min_length": settings.min_password_length,
            "max_length": settings.max_password_length,
            "require_uppercase": settings.require_uppercase,
            "require_lowercase": settings.require_lowercase,
            "require_number": settings.require_number,
            "require_special": settings.require_special_char,
        },
        "session_security": {
            "logout_on_password_change": settings.logout_on_password_change,
            "max_concurrent_sessions": settings.max_concurrent_sessions,
            "session_timeout_minutes": settings.session_timeout_minutes,
        },
        "token_expiry": {
            "access_token_minutes": settings.access_token_expire_minutes,
            "refresh_token_days": settings.refresh_token_expire_days,
        },
        "file_upload": {
            "max_size_bytes": settings.max_upload_size,
            "allowed_extensions": settings.allowed_file_extensions,
        },
    }
