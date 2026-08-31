from typing import Optional
from app.core.config import get_settings
from app.services.email.client import _send
from app.services.email.templates import _premium_template, BRAND

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


async def send_password_reset_email(to: str, full_name: str, reset_link: str) -> bool:
    body = f"""
    <p>Dear {full_name},</p>
    <p>We received a request to reset your Rental Garage password.</p>
    <p>Click the button below to set a new password. This link expires in <strong>15 minutes</strong>.</p>
    
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
