import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.exc import UnknownHashError
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.config import get_settings
from app.core.security import create_access_token, get_password_hash, normalize_email, verify_password
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import get_subscription_warning
from app.models.password_reset import PasswordResetToken
from app.models.users import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenOut,
)
from app.schemas.user import UserOut
from app.services.email import (
    send_password_reset_email,
    send_password_reset_success,
)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])
RESET_TOKEN_EXPIRE_MINUTES = 15

# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

def _get_valid_reset_token_or_400(token: str, db: Session) -> PasswordResetToken:
    """Helper to validate token existence, usage status, and expiration."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at == None,
    ).first()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    now = datetime.now(timezone.utc)
    expires_at = db_token.expires_at if db_token.expires_at.tzinfo else db_token.expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired. Please request a new one.",
        )
    return db_token

def _get_active_user_or_400(user_id: int, db: Session) -> User:
    """Helper to verify user exists and is active for password reset."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return user

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenOut)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    email = normalize_email(credentials.email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    password_matches = False
    try:
        password_matches = verify_password(credentials.password, user.password_hash)
    except (UnknownHashError, ValueError, TypeError):
        password_matches = credentials.password == user.password_hash

    if not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    if user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended. Please contact your administrator.",
        )

    # Upgrade legacy plaintext passwords to bcrypt
    if not user.password_hash.startswith("$2"):
        user.password_hash = get_password_hash(credentials.password)
        db.commit()

    # ✅ CRITICAL FIX: Removed trailing spaces from JWT claims keys
    access_token = create_access_token(
        subject=str(user.id),
        claims={
            "tenant_id": user.tenant_id,
            "role": user.role,
        },
    )

    # ✅ CRITICAL FIX: Removed trailing space from token_type
    return TokenOut(access_token=access_token, token_type="bearer", user=user)

@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/me/subscription-status")
def get_my_subscription_status(
    current_user: User = Depends(get_current_user),
    warning: dict | None = Depends(get_subscription_warning),
):
    tenant = current_user.tenant
    if tenant is None:
        return {"subscription_status": None, "warning": None}
    return {
        "subscription_status": tenant.subscription_status,
        "trial_ends_at": tenant.trial_ends_at,
        "subscription_ends_at": tenant.subscription_ends_at,
        "grace_period_ends_at": tenant.grace_period_ends_at,
        "plan": tenant.plan,
        "warning": warning,
    }

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    email = normalize_email(payload.email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    
    if not user or not user.is_active:
        return {"message": "If that email exists, a reset link has been sent"}

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at == None,
    ).delete()
    db.commit()

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    db_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()

    reset_link = f"{settings.frontend_url}/reset-password?token={raw_token}"
    send_password_reset_email(
        to=user.email,
        full_name=user.full_name,
        reset_link=reset_link,
    )

    return {"message": "If that email exists, a reset link has been sent"}

@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    db_token = _get_valid_reset_token_or_400(payload.token, db)
    user = _get_active_user_or_400(db_token.user_id, db)

    user.password_hash = get_password_hash(payload.new_password)
    db_token.used_at = datetime.now(timezone.utc)
    db.commit()

    send_password_reset_success(
        to=user.email,
        full_name=user.full_name,
    )

    return {"message": "Password reset successfully. You can now log in with your new password."}
