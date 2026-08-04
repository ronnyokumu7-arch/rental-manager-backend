import logging
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Gracefully handle whichever JWT package is actually installed
try:
    from jwt.exceptions import PyJWTError, ExpiredSignatureError, DecodeError
    JWT_ERRORS = (PyJWTError, ExpiredSignatureError, DecodeError)
except ImportError:
    # Fallback if the wrong 'jwt' package is installed
    JWT_ERRORS = (Exception,)

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"

# ✅ NEW: Initialize Fernet cipher for encrypting sensitive DB fields (e.g., payment secrets)
# This ensures tenant payment credentials are never stored in plain text, 
# protecting them even from DB admins or accidental log leaks.
cipher_suite = Fernet(settings.ENCRYPTION_KEY.encode())


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_password_hash(password: str) -> str:
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password = password_bytes[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(subject: str, claims: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "type": "access",  # ✅ THIS LINE WAS MISSING
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWT_ERRORS:
        return None


# =============================================================================
# ✅ NEW: Encryption utilities for sensitive tenant data (Payment Gateway Secrets)
# =============================================================================

def encrypt_secret(plain_text: str) -> str:
    """
    Encrypts a sensitive string (e.g., API secret, webhook secret, passkey) using Fernet.
    Returns a URL-safe base64 encoded string suitable for database storage.
    """
    if not plain_text:
        return ""
    return cipher_suite.encrypt(plain_text.encode()).decode()


def decrypt_secret(encrypted_text: str) -> str:
    """
    Decrypts a Fernet-encrypted string.
    Returns the original plain text string.
    Raises ValueError if decryption fails (e.g., tampered data or wrong encryption key).
    """
    if not encrypted_text:
        return ""
    try:
        return cipher_suite.decrypt(encrypted_text.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt secret: Invalid token or corrupted data.")
        # We raise a generic ValueError to avoid leaking specific crypto details to the caller,
        # but the logger captures the actual issue for the backend team.
        raise ValueError("Failed to decrypt sensitive data. The data may be corrupted or the encryption key has changed.")
