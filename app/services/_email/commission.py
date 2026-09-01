# app/services/_email/commission.py
"""
✅ COMMISSION EMAIL SERVICE

Sends daily commission statements with escalating severity.
"""
import os
from decimal import Decimal
from app.services._email.client import _send
from app.services._email.templates import _premium_template, BRAND


async def send_commission_statement(
    to: str,
    tenant_name: str,
    trip_count: int,
    total: Decimal,
    days_until_lock: int,
    paybill: str | None = None,
    account_number: str | None = None,
    account_name: str | None = None,
) -> bool:
    """
    Sends a commission statement with escalating severity:
    - days_until_lock > 2: Daily statement
    - days_until_lock 1–2: Warning
    - days_until_lock == 0: Lock notice
    """
    # Determine severity
    if days_until_lock == 0:
        title = "Account Soft-Locked"
        color = "#e11d48"  # red
        severity_emoji = "🔒"
    elif days_until_lock <= 2:
        title = f"{days_until_lock} Day(s) Until Soft-Lock"
        color = "#d97706"  # amber
        severity_emoji = "⚠️"
    else:
        title = "Daily Commission Statement"
        color = "#2563eb"  # blue
        severity_emoji = "📄"

    # Build payment details block
    paybill_block = ""
    if paybill and account_number:
        paybill_block = f"""
        <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 16px 0;">
            <p style="margin: 0 0 8px 0; font-weight: 600;">Payment Details:</p>
            <p style="margin: 4px 0;"><strong>PayBill:</strong> {paybill}</p>
            <p style="margin: 4px 0;"><strong>Account No:</strong> {account_number}</p>
            {f'<p style="margin: 4px 0;"><strong>Account Name:</strong> {account_name}</p>' if account_name else ''}
        </div>
        """
    else:
        paybill_block = """
        <p style="margin: 16px 0; color: #6b7280; font-size: 13px;">
            Payment details are available in your dashboard under <strong>Commission → Pay</strong>.
        </p>
        """

    # Build CTA link
    pay_url = os.getenv("FRONTEND_URL", "")
    cta_url = f"{pay_url}/commission/pay" if pay_url else ""

    # Build email body
    body = f"""
    <p>Hi {tenant_name},</p>
    
    <div style="background: {color}10; border-left: 4px solid {color}; padding: 12px 16px; margin: 16px 0;">
        <p style="margin: 0; font-size: 15px;">
            <strong>{severity_emoji} {title}</strong>
        </p>
    </div>
    
    <p style="margin: 16px 0;">
        You have <strong>{trip_count}</strong> unpaid trip(s) totalling <strong style="color: {color};">KES {total:,.2f}</strong>.
    </p>
    
    {paybill_block}
    
    <p style="margin-top: 24px; font-size: 13px; color: #78716c;">
        If you've already settled this amount, please disregard this email.
    </p>
    """

    # Determine CTA text
    cta_text = "Pay Commission Now" if days_until_lock <= 2 else "View Commission Dashboard"

    return await _send(
        to,
        f"{severity_emoji} {tenant_name}: {title} — KES {total:,.0f} Outstanding",
        _premium_template(
            title=title,
            body=body,
            cta_text=cta_text,
            cta_url=cta_url,
            preview_text=f"{trip_count} unpaid trips totalling KES {total:,.0f}",
        )
    )
