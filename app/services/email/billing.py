from app.core.config import get_settings
from app.services.email.client import _send
from app.services.email.templates import _premium_template, BRAND

settings = get_settings()


async def send_invoice_notification(
    to: str, company_name: str, invoice_number: str, amount_due: str, currency: str, due_date: str,
) -> bool:
    body = f"""
    <p>Dear {company_name},</p>
    <p>A new invoice has been issued for your Rental Garage subscription.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Invoice Number</td><td>{invoice_number}</td></tr>
        <tr><td>Amount Due</td><td><strong>{currency} {amount_due}</strong></td></tr>
        <tr><td>Due Date</td><td>{due_date}</td></tr>
    </table>
    
    <p>Please log in to your portal to view and pay this invoice before the due date to avoid service interruption.</p>
    """
    return await _send(
        to,
        f"Invoice {invoice_number} — Payment Due",
        _premium_template(
            title="Invoice Issued",
            body=body,
            cta_text="View & Pay Invoice",
            cta_url=f"{settings.frontend_url}/invoices",
            preview_text=f"Invoice {invoice_number} is now available.",
        )
    )


async def send_payment_received(
    to: str, company_name: str, invoice_number: str, amount_paid: str, currency: str,
) -> bool:
    body = f"""
    <p>Dear {company_name},</p>
    <p><strong>Payment received!</strong> Thank you for your payment.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Invoice Number</td><td>{invoice_number}</td></tr>
        <tr><td>Amount Paid</td><td><strong>{currency} {amount_paid}</strong></td></tr>
        <tr><td>Status</td><td><span class="badge badge-confirmed">Paid</span></td></tr>
    </table>
    
    <p>Your account is now up to date. Thank you for being a valued customer!</p>
    """
    return await _send(
        to,
        f"Payment Received — {invoice_number}",
        _premium_template(
            title="Payment Received",
            body=body,
            cta_text="View Payment Details",
            cta_url=f"{settings.frontend_url}/invoices",
            preview_text="Thank you for your payment.",
        )
    )


async def send_trial_ending_warning(
    to: str, company_name: str, days_left: int, trial_ends_at: str,
) -> bool:
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your free trial is ending soon.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Days Remaining</td><td><strong>{days_left}</strong></td></tr>
        <tr><td>Trial Ends</td><td>{trial_ends_at}</td></tr>
    </table>
    
    <div style="margin-top: 16px; padding: 16px; background: {BRAND['warning_bg']}; border-radius: 8px; border-left: 3px solid {BRAND['warning']};">
        <strong>⚠️ Action Required:</strong> To continue using Rental Garage without interruption, please choose a plan and settle your invoice before the trial ends.
    </div>
    
    <p style="margin-top: 16px;">After your trial, your account will move to a 14-day starter trial before being suspended if no plan is selected.</p>
    """
    return await _send(
        to,
        "Your Trial Is Ending Soon",
        _premium_template(
            title="Trial Ending Soon",
            body=body,
            cta_text="Choose a Plan",
            cta_url=f"{settings.frontend_url}/subscription",
            preview_text=f"Your trial ends in {days_left} days.",
        )
    )


async def send_subscription_past_due(
    to: str, company_name: str, grace_period_ends_at: str,
) -> bool:
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your Rental Garage subscription is <strong>past due</strong>.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Grace Period Ends</td><td>{grace_period_ends_at}</td></tr>
        <tr><td>Status</td><td><span class="badge badge-pending">Past Due</span></td></tr>
    </table>
    
    <div style="margin-top: 16px; padding: 16px; background: {BRAND['danger_bg']}; border-radius: 8px; border-left: 3px solid {BRAND['danger']};">
        <strong>⚠️ Urgent:</strong> You have until the date above to settle your invoice before your account is suspended.
    </div>
    
    <p style="margin-top: 16px;">During this grace period you can still view your data but cannot add new clients, vehicles, or bookings.</p>
    """
    return await _send(
        to,
        "Action Required — Subscription Past Due",
        _premium_template(
            title="Subscription Past Due",
            body=body,
            cta_text="Pay Now",
            cta_url=f"{settings.frontend_url}/invoices",
            preview_text="Your subscription is past due.",
        )
    )


async def send_subscription_suspended(
    to: str, company_name: str,
) -> bool:
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your Rental Garage account has been <strong>suspended</strong> due to non-payment.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Status</td><td><span class="badge badge-cancelled">Suspended</span></td></tr>
    </table>
    
    <div style="margin-top: 16px; padding: 16px; background: {BRAND['danger_bg']}; border-radius: 8px; border-left: 3px solid {BRAND['danger']};">
        <strong>⚠️ Action Required:</strong> You can still log in and view your existing data, but you cannot add or modify records until your invoice is settled.
    </div>
    
    <p style="margin-top: 16px;">Please contact support or log in to pay your outstanding invoice to reactivate your account.</p>
    """
    return await _send(
        to,
        "Account Suspended — Action Required",
        _premium_template(
            title="Account Suspended",
            body=body,
            cta_text="Reactivate Account",
            cta_url=f"{settings.frontend_url}/invoices",
            preview_text="Your account has been suspended.",
        )
    )
