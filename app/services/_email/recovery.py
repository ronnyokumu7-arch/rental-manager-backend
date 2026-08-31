from typing import Optional
from app.core.config import get_settings
from app.services._email.client import _send
from app.services._email.templates import _premium_template, BRAND

settings = get_settings()


async def send_admin_recovery_notification(
    to: str,
    admin_name: str,
    recovery_link: str,
    tenant_name: str = "Rental Garage"
) -> bool:
    """
    Sends a recovery notification to an admin.
    """
    body = f"""
    <p>Dear {admin_name},</p>
    <p><strong>Admin Recovery Request</strong></p>
    <p>We received a request to recover admin access for <strong>{tenant_name}</strong>.</p>
    <p>Click the button below to complete the recovery process. This link expires in <strong>15 minutes</strong>.</p>
    
    <p style="margin-top: 16px; font-size: 13px; color: #78716C;">
        If you did not request this recovery, please contact support immediately.
    </p>
    <p style="font-size: 12px; color: #A8A39E;">
        Or copy this link into your browser:<br>
        <span style="color: {BRAND['primary']}; word-break: break-all;">{recovery_link}</span>
    </p>
    """
    return await _send(
        to,
        f"Admin Recovery Request - {tenant_name}",
        _premium_template(
            title="Admin Recovery Request",
            body=body,
            cta_text="Recover Admin Access",
            cta_url=recovery_link,
            preview_text="Admin recovery request received.",
        )
    )


async def send_sms_otp(
    phone_number: str,
    otp: str,
    tenant_name: str = "Rental Garage"
) -> bool:
    """
    Sends an OTP via SMS (placeholder - integrate with SMS service).
    
    Note: This is a placeholder function. You'll need to integrate with an SMS provider
    like Twilio, Vonage, or Africa's Talking for actual SMS delivery.
    """
    # TODO: Integrate with actual SMS provider
    # Example with Twilio:
    # from twilio.rest import Client
    # client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    # message = client.messages.create(
    #     body=f"Your {tenant_name} verification code is: {otp}",
    #     from_=settings.twilio_phone_number,
    #     to=phone_number
    # )
    
    # For now, log the OTP and return True (simulate success)
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"SMS OTP sent to {phone_number}: {otp}")
    
    # If you want to actually send via email as a fallback (useful for testing)
    # Uncomment below to also send OTP via email (for testing purposes)
    # await _send(
    #     settings.admin_email,
    #     f"SMS OTP for {phone_number}",
    #     f"Your verification code is: <strong>{otp}</strong>"
    # )
    
    return True
