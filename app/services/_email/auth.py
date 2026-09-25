from typing import Optional
from app.core.config import get_settings
from app.services._email.client import _send
from app.services._email.templates import _premium_template, BRAND

settings = get_settings()


async def send_welcome_email(
    to: str, 
    full_name: str, 
    role: str, 
    temp_password: Optional[str] = None,
    tenant_name: str = "Rental Garage"
) -> bool:
    # ✅ Conditionally render the password row only if a temp password is provided
    password_row = ""
    if temp_password:
        password_row = f"""
        <tr>
            <td>Temporary Password</td>
            <td><strong style="font-family: 'JetBrains Mono', monospace; letter-spacing: 0.05em;">{temp_password}</strong></td>
        </tr>
        """

    body = f"""
    <p>Dear {full_name},</p>
    <p><strong>Welcome to {tenant_name}!</strong></p>
    <p>Your account has been created. You're now ready to start managing your fleet operations.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Email</td><td>{to}</td></tr>
        <tr><td>Role</td><td>{role.replace('_', ' ').title()}</td></tr>
        {password_row}
    </table>
    
    <p>Please log in and change your password immediately. We recommend choosing a strong, unique password.</p>
    """
    return await _send(
        to,
        f"Welcome to {tenant_name}",
        _premium_template(
            title="Welcome!",
            body=body,
            cta_text="Log In Now",
            cta_url=f"{settings.frontend_url}/login",
            preview_text="Your account has been created.",
        )
    )


async def send_password_changed(to: str, full_name: str) -> bool:
    body = f"""
    <p>Dear {full_name},</p>
    <p>Your Rental Garage password was recently changed.</p>
    <p>If you did not make this change, please contact your administrator immediately.</p>
    """
    return await _send(
        to,
        "Password Changed",
        _premium_template(
            title="Password Changed",
            body=body,
            preview_text="Your password was updated.",
        )
    )


def _format_ttl(minutes: int) -> str:
    """Formats TTL for email display (60 → '1 hour', 120 → '2 hours', else 'X minutes')."""
    if minutes >= 60:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours > 1 else ''}"
    return f"{minutes} minutes"


async def send_password_reset_email(to: str, full_name: str, reset_link: str) -> bool:
    # ✅ TTL now matches the actual config value (default 60 min)
    ttl_display = _format_ttl(settings.password_reset_token_expire_minutes)
    
    body = f"""
    <p>Dear {full_name},</p>
    <p>We received a request to reset your Rental Garage password.</p>
    <p>Click the button below to set a new password. This link expires in <strong>{ttl_display}</strong>.</p>
    
    <p style="margin-top: 16px; font-size: 13px; color: #78716C;">
        If you did not request a password reset, you can safely ignore this email. Your password will not change.
    </p>
    <p style="font-size: 12px; color: #A8A39E;">
        Or copy this link into your browser:<br>
        <span style="color: {BRAND['primary']}; word-break: break-all;">{reset_link}</span>
    </p>
    """
    return await _send(
        to,
        "Reset Your Rental Garage Password",
        _premium_template(
            title="Password Reset Request",
            body=body,
            cta_text="Reset My Password",
            cta_url=reset_link,
            preview_text="Reset your password securely.",
        )
    )


async def send_password_reset_success(to: str, full_name: str) -> bool:
    body = f"""
    <p>Dear {full_name},</p>
    <p>Your Rental Garage password has been successfully reset.</p>
    <p>If you did not make this change, please contact your administrator immediately.</p>
    """
    return await _send(
        to,
        "Your Password Has Been Reset",
        _premium_template(
            title="Password Reset Successful",
            body=body,
            preview_text="Your password was reset successfully.",
        )
    )


async def send_verification_email(to: str, full_name: str, verification_link: str) -> bool:
    body = f"""
    <p>Dear {full_name},</p>
    <p><strong>Welcome to Rental Garage!</strong></p>
    <p>To complete your account setup and ensure the security of your data, please verify your email address.</p>
    
    <p style="margin-top: 16px; font-size: 13px; color: #78716C;">
        If you did not request this verification, you can safely ignore this email.
    </p>
    <p style="font-size: 12px; color: #A8A39E;">
        Or copy and paste this link into your browser:<br>
        <span style="color: {BRAND['primary']}; word-break: break-all;">{verification_link}</span>
    </p>
    """
    return await _send(
        to,
        "Verify Your Rental Garage Account",
        _premium_template(
            title="Account Verification",
            body=body,
            cta_text="Verify My Account",
            cta_url=verification_link,
            preview_text="Please verify your email address.",
        )
    )


# ✅ NEW: Investor Invite Email
async def send_investor_invite_email(
    to: str, full_name: str, invite_token: str, agency_name: str, expires_at: str
) -> bool:
    invite_link = f"{settings.frontend_url}/investor/accept-invite?token={invite_token}"
    
    body = f"""
    <p>Dear Investor,</p>
    <p><strong>{agency_name}</strong> has invited you to join their fleet as a Host Investor on Rental Garage.</p>
    <p>By joining, you will be able to list your vehicles, track bookings in real-time, and manage your earnings seamlessly.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Inviting Agency</td><td><strong>{agency_name}</strong></td></tr>
        <tr><td>Invite Expires</td><td>{expires_at.split('T')[0]}</td></tr>
    </table>
    
    <p>Click the button below to create your investor profile and list your first vehicle.</p>
    """
    return await _send(
        to,
        f"Invitation to join {agency_name} on Rental Garage",
        _premium_template(
            title="You're Invited!",
            body=body,
            cta_text="Accept Invitation",
            cta_url=invite_link,
            preview_text=f"{agency_name} wants you to join their fleet.",
        )
    )
