from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.schemas.tenant_recovery import SendResetLinkPayload
from app.services.email import send_admin_recovery_notification, send_sms_otp
from app.services.activity_log import ActivityLogService
from ._helpers import _get_user_or_404

router = APIRouter()

admin_or_above = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))


def _mask_email(email: str) -> str:
    """Masks email for safe display (e.g., j***@example.com)."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[0]}***@{domain}" if len(local) > 1 else f"***@{domain}"


def _mask_phone(phone: str | None) -> str | None:
    """Masks phone for safe display (e.g., +254 *** *** 7890)."""
    if not phone or len(phone) < 10:
        return None
    return f"{phone[:-7]} *** *** {phone[-4:]}"


# =============================================================================
# 1. GET RECOVERY OPTIONS (GET /{user_id}/recovery-options)
# =============================================================================
@router.get("/{user_id}/recovery-options")
@limiter.limit("30/minute")
async def get_user_recovery_options(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """
    Returns masked recovery contact info for a user. 
    Useful for admins to verify which channel to use before triggering a reset.
    """
    user = await _get_user_or_404(user_id, db)

    # ✅ Tenant isolation check: Tenant admins can only view users in their own tenant.
    # Super admins bypass this check (current_user.role != UserRole.tenant_admin).
    if current_user.role == UserRole.tenant_admin and user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return {
        "email_masked": _mask_email(user.email),
        "phone_masked": _mask_phone(user.phone_number),
        "phone_verified": user.phone_verified,
        "two_factor_enabled": user.two_factor_enabled,
        # ✅ Clean, safe datetime formatting
        "account_locked_until": user.account_locked_until.isoformat() if user.account_locked_until else None,
    }


# =============================================================================
# 2. SEND RESET LINK NUDGE (POST /{user_id}/send-reset-link)
# =============================================================================
@router.post("/{user_id}/send-reset-link", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")  # 🚨 STRICT: Prevents spamming recovery notifications
async def send_user_reset_link(
    request: Request,
    user_id: int,
    payload: SendResetLinkPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_or_above,
):
    """
    Admin-triggered notification nudge. 
    Sends an email/SMS prompting the user to check their inbox for reset instructions.
    
    NOTE: This does NOT generate a password reset token. It relies on the user 
    subsequently using the public /auth/forgot-password flow, or it serves as 
    a manual nudge if the admin has already generated a secure link out-of-band.
    """
    user = await _get_user_or_404(user_id, db)

    # ✅ Tenant isolation check
    if current_user.role == UserRole.tenant_admin and user.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # ✅ BUSINESS LOGIC: Do not send recovery nudges to inactive/suspended accounts
    if not user.is_active or user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Cannot send recovery instructions to an inactive or suspended account."
        )

    # ✅ Trigger notifications safely
    if payload.send_to_email and user.email:
        send_admin_recovery_notification(
            to=user.email,
            full_name=user.full_name,
            subject="Password Reset Requested",
            custom_message=payload.custom_message or "A password reset has been requested for your account. Please check your email for instructions.",
        )

    if payload.send_to_phone and user.phone_number:
        send_sms_otp(
            phone=user.phone_number,
            message="Password reset requested for your Rental Manager account. Please check your email for instructions.",
        )

    # ✅ Log the admin action for audit purposes
    await ActivityLogService.log(
        db=db, tenant_id=user.tenant_id or 0, user_id=current_user.id,
        action="trigger_user_reset_link", target_type="user", target_id=user.id,
        details={
            "user_email": user.email, 
            "channels": {"email": payload.send_to_email, "phone": payload.send_to_phone}
        }
    )
    await db.commit()  # Commit the activity log flush

    return {"message": "Reset instructions sent successfully."}
