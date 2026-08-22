import logging
import uuid
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

# ✅ Fernet cipher for encrypting sensitive DB fields (e.g., payment secrets)
cipher_suite = Fernet(settings.ENCRYPTION_KEY.encode())


# =============================================================================
# ✅ SECURITY AUDIT LOGGER
# =============================================================================

class SecurityAuditLogger:
    """
    Structured security event logging for forensic analysis and attack detection.
    All security-relevant events are logged with consistent structure.
    """
    
    @staticmethod
    def log_login_success(user_id: int, email: str, ip: str):
        logger.info(
            "SECURITY_EVENT: LOGIN_SUCCESS",
            extra={
                "event": "login_success",
                "user_id": user_id,
                "email": email,
                "ip": ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    
    @staticmethod
    def log_login_failure(email: str, ip: str, reason: str = "invalid_credentials"):
        logger.warning(
            "SECURITY_EVENT: LOGIN_FAILURE",
            extra={
                "event": "login_failure",
                "email": email,
                "ip": ip,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    
    @staticmethod
    def log_token_refresh(user_id: int, ip: str):
        logger.info(
            "SECURITY_EVENT: TOKEN_REFRESH",
            extra={
                "event": "token_refresh",
                "user_id": user_id,
                "ip": ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    
    @staticmethod
    def log_account_locked(email: str, ip: str):
        logger.warning(
            "SECURITY_EVENT: ACCOUNT_LOCKED",
            extra={
                "event": "account_locked",
                "email": email,
                "ip": ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    
    @staticmethod
    def log_password_change(user_id: int, ip: str):
        logger.info(
            "SECURITY_EVENT: PASSWORD_CHANGE",
            extra={
                "event": "password_change",
                "user_id": user_id,
                "ip": ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    
    @staticmethod
    def log_sensitive_operation(user_id: int, operation: str, ip: str):
        logger.info(
            "SECURITY_EVENT: SENSITIVE_OPERATION",
            extra={
                "event": "sensitive_operation",
                "user_id": user_id,
                "operation": operation,
                "ip": ip,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


# Instantiate audit logger for easy access
security_audit = SecurityAuditLogger()


# =============================================================================
# ✅ EMAIL UTILITIES
# =============================================================================

def normalize_email(email: str) -> str:
    """
    Normalizes email address to prevent case-sensitivity bypass attacks.
    Example: "User@Example.COM" -> "user@example.com"
    """
    return email.strip().lower()


# =============================================================================
# ✅ PASSWORD SECURITY
# =============================================================================

def get_password_hash(password: str) -> str:
    """
    Hashes a password using bcrypt.
    Handles bcrypt's 72-byte input limit gracefully.
    """
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        # Truncate to 72 bytes (bcrypt limit)
        password = password_bytes[:72].decode('utf-8', errors='ignore')
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verifies a plain password against its bcrypt hash.
    Returns True if valid, False otherwise.
    """
    try:
        return pwd_context.verify(plain_password, password_hash)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


# =============================================================================
# ✅ JWT ACCESS TOKENS
# =============================================================================

def create_access_token(subject: str, claims: dict | None = None) -> str:
    """
    Creates a short-lived JWT access token.
    
    Args:
        subject: User ID or identifier
        claims: Additional claims to include in the token
        
    Returns:
        Encoded JWT string
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    
    payload = {
        "sub": subject,
        "type": "access",  # ✅ CRITICAL: Token type validation
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),  # ✅ Unique ID for potential revocation
    }
    
    if claims:
        payload.update(claims)
    
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    Decodes and validates a JWT access token.
    
    Returns None if:
    - Token is malformed
    - Token is expired
    - Token type is not 'access'
    - Token is missing required claims
    
    Returns payload dict if valid.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        
        # ✅ CRITICAL: Validate token type
        if payload.get("type") != "access":
            logger.warning(f"Invalid token type: {payload.get('type')}")
            return None
        
        # ✅ CRITICAL: Validate subject exists
        if not payload.get("sub"):
            logger.warning("Token missing subject claim")
            return None
        
        # ✅ CRITICAL: Validate expiry (jwt.decode already does this, but double-check)
        if payload.get("exp") and payload["exp"] < datetime.now(timezone.utc).timestamp():
            logger.warning("Token expired")
            return None
        
        return payload
        
    except JWT_ERRORS as e:
        logger.warning(f"JWT decode failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected JWT error: {e}")
        return None


# =============================================================================
# ✅ JWT REFRESH TOKENS
# =============================================================================

def create_refresh_token(subject: str, claims: dict | None = None) -> str:
    """
    Creates a long-lived JWT refresh token.
    
    Args:
        subject: User ID or identifier
        claims: Additional claims to include in the token
        
    Returns:
        Encoded JWT string
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    
    payload = {
        "sub": subject,
        "type": "refresh",  # ✅ Different type from access tokens
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),  # ✅ Unique ID for revocation support
    }
    
    if claims:
        payload.update(claims)
    
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> dict | None:
    """
    Decodes and validates a JWT refresh token.
    
    Returns None if:
    - Token is malformed
    - Token is expired
    - Token type is not 'refresh'
    - Token is missing required claims
    
    Returns payload dict if valid.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        
        # ✅ CRITICAL: Validate token type
        if payload.get("type") != "refresh":
            logger.warning(f"Invalid refresh token type: {payload.get('type')}")
            return None
        
        # ✅ CRITICAL: Validate subject exists
        if not payload.get("sub"):
            logger.warning("Refresh token missing subject claim")
            return None
        
        return payload
        
    except JWT_ERRORS as e:
        logger.warning(f"Refresh token decode failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected refresh token error: {e}")
        return None


# =============================================================================
# ✅ SENSITIVE DATA ENCRYPTION (Payment Gateway Secrets)
# =============================================================================

def encrypt_secret(plain_text: str) -> str:
    """
    Encrypts a sensitive string (e.g., API secret, webhook secret, passkey) using Fernet.
    Returns a URL-safe base64 encoded string suitable for database storage.
    
    Args:
        plain_text: The sensitive data to encrypt
        
    Returns:
        Encrypted string (safe for DB storage)
    """
    if not plain_text:
        return ""
    
    try:
        return cipher_suite.encrypt(plain_text.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise ValueError("Failed to encrypt sensitive data")


def decrypt_secret(encrypted_text: str) -> str:
    """
    Decrypts a Fernet-encrypted string.
    Returns the original plain text string.
    
    Args:
        encrypted_text: The encrypted data to decrypt
        
    Returns:
        Decrypted plain text string
        
    Raises:
        ValueError: If decryption fails (tampered data or wrong encryption key)
    """
    if not encrypted_text:
        return ""
    
    try:
        return cipher_suite.decrypt(encrypted_text.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt secret: Invalid token or corrupted data.")
        raise ValueError(
            "Failed to decrypt sensitive data. "
            "The data may be corrupted or the encryption key has changed."
        )
    except Exception as e:
        logger.error(f"Unexpected decryption error: {e}")
        raise ValueError("Failed to decrypt sensitive data")


# =============================================================================
# ✅ TOKEN UTILITIES
# =============================================================================

def is_token_expired(payload: dict) -> bool:
    """
    Checks if a token payload is expired.
    
    Args:
        payload: Decoded JWT payload
        
    Returns:
        True if expired, False otherwise
    """
    if not payload.get("exp"):
        return True
    
    now = datetime.now(timezone.utc).timestamp()
    return payload["exp"] < now


def get_token_expiry(payload: dict) -> datetime | None:
    """
    Gets the expiry datetime from a token payload.
    
    Args:
        payload: Decoded JWT payload
        
    Returns:
        Datetime object or None if no expiry
    """
    if not payload.get("exp"):
        return None
    
    try:
        return datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def generate_token_id() -> str:
    """
    Generates a unique token ID (jti claim).
    Used for token revocation tracking.
    
    Returns:
        UUID string
    """
    return str(uuid.uuid4())


# =============================================================================
# ✅ SECURITY VALIDATION HELPERS
# =============================================================================

def validate_token_structure(token: str) -> bool:
    """
    Validates basic JWT structure without decoding.
    Useful for quick rejection of malformed tokens.
    
    Args:
        token: JWT string to validate
        
    Returns:
        True if structure is valid, False otherwise
    """
    if not token or not isinstance(token, str):
        return False
    
    parts = token.split('.')
    return len(parts) == 3


def sanitize_log_message(message: str) -> str:
    """
    Sanitizes log messages to prevent log injection attacks.
    Removes newlines, carriage returns, and other control characters.
    
    Args:
        message: Raw log message
        
    Returns:
        Sanitized message safe for logging
    """
    if not message:
        return ""
    
    # Remove control characters that could be used for log injection
    return message.replace('\n', '').replace('\r', '').replace('\t', '')


def validate_email_format(email: str) -> bool:
    """
    Basic email format validation to prevent injection attacks.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if format appears valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    
    # Basic sanity checks
    if len(email) > 254:  # RFC 5321 limit
        return False
    
    if '@' not in email:
        return False
    
    local, _, domain = email.partition('@')
    
    if not local or not domain:
        return False
    
    if len(local) > 64:  # RFC 5321 limit
        return False
    
    return True


def validate_user_id(user_id: int | str) -> bool:
    """
    Validates user ID to prevent injection or overflow attacks.
    
    Args:
        user_id: User ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        uid = int(user_id)
        return 1 <= uid <= 999999999  # Reasonable range
    except (ValueError, TypeError):
        return False
