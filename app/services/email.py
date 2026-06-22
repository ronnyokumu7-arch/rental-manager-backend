import logging
from typing import Optional

import resend

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

resend.api_key = settings.resend_api_key


def _send(to: str | list[str], subject: str, html: str) -> bool:
    try:
        resend.Emails.send({
            "from": f"{settings.from_name} <{settings.from_email}>",
            "to": to if isinstance(to, list) else [to],
            "subject": subject,
            "html": html,
        })
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def _base_template(title: str, body: str, footer: str = "") -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
        .container {{ max-width: 600px; margin: 40px auto; background: #ffffff; border-radius: 8px; overflow: hidden; }}
        .header {{ background: #1a1a2e; padding: 28px 32px; }}
        .header h1 {{ color: #ffffff; margin: 0; font-size: 20px; font-weight: 600; }}
        .header p {{ color: #9999bb; margin: 4px 0 0; font-size: 13px; }}
        .body {{ padding: 32px; color: #333333; font-size: 15px; line-height: 1.6; }}
        .body h2 {{ font-size: 17px; color: #1a1a2e; margin-top: 0; }}
        .detail-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .detail-table td {{ padding: 10px 12px; border-bottom: 1px solid #eeeeee; font-size: 14px; }}
        .detail-table td:first-child {{ color: #888888; width: 40%; }}
        .detail-table td:last-child {{ font-weight: 600; color: #1a1a2e; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 99px; font-size: 12px; font-weight: 600; }}
        .badge-blue {{ background: #e6f0ff; color: #1a56db; }}
        .badge-green {{ background: #e6f9f0; color: #0e7c4a; }}
        .badge-red {{ background: #fde8e8; color: #c81e1e; }}
        .badge-amber {{ background: #fef3c7; color: #92400e; }}
        .btn {{ display: inline-block; margin-top: 20px; padding: 12px 28px; background: #1a1a2e; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600; }}
        .footer {{ padding: 20px 32px; background: #f9f9f9; border-top: 1px solid #eeeeee; font-size: 12px; color: #aaaaaa; }}
    </style>
    </head>
    <body>
    <div class="container">
        <div class="header">
            <h1>Rental Manager</h1>
            <p>Vehicle Rental Management Platform</p>
        </div>
        <div class="body">
            <h2>{title}</h2>
            {body}
        </div>
        <div class="footer">
            {footer or "This is an automated message from Rental Manager. Please do not reply to this email."}
        </div>
    </div>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Booking emails
# ---------------------------------------------------------------------------

def send_booking_confirmation(
    to: str,
    client_name: str,
    booking_id: int,
    vehicle: str,
    start_date: str,
    end_date: str,
    total_amount: str,
    currency: str,
    contract_number: str,
):
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your booking has been received and is currently <span class="badge badge-amber">Pending</span> confirmation.</p>
    <table class="detail-table">
        <tr><td>Booking ID</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Start date</td><td>{start_date}</td></tr>
        <tr><td>End date</td><td>{end_date}</td></tr>
        <tr><td>Total amount</td><td>{currency} {total_amount}</td></tr>
        <tr><td>Contract No.</td><td>{contract_number}</td></tr>
    </table>
    <p>We will notify you once your booking is confirmed. Please review your rental agreement carefully.</p>
    """
    return _send(to, f"Booking #{booking_id} Received", _base_template("Booking Received", body))


def send_booking_confirmed(
    to: str,
    client_name: str,
    booking_id: int,
    vehicle: str,
    start_date: str,
):
    body = f"""
    <p>Dear {client_name},</p>
    <p>Great news! Your booking is now <span class="badge badge-green">Confirmed</span>.</p>
    <table class="detail-table">
        <tr><td>Booking ID</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Pickup date</td><td>{start_date}</td></tr>
    </table>
    <p>Please ensure you bring your valid driver's licence and ID on pickup day.</p>
    """
    return _send(to, f"Booking #{booking_id} Confirmed", _base_template("Booking Confirmed", body))


def send_booking_activated(
    to: str,
    client_name: str,
    booking_id: int,
    vehicle: str,
    end_date: str,
):
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental is now <span class="badge badge-blue">Active</span>. Enjoy your drive!</p>
    <table class="detail-table">
        <tr><td>Booking ID</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Return by</td><td>{end_date}</td></tr>
    </table>
    <p>Please return the vehicle by the date above. Late returns will be charged at the daily rate.</p>
    """
    return _send(to, f"Your Rental Has Started — #{booking_id}", _base_template("Rental Active", body))


def send_booking_completed(
    to: str,
    client_name: str,
    booking_id: int,
    vehicle: str,
):
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental has been <span class="badge badge-green">Completed</span>. Thank you for choosing us!</p>
    <table class="detail-table">
        <tr><td>Booking ID</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
    </table>
    <p>We hope you had a great experience. We look forward to serving you again.</p>
    """
    return _send(to, f"Rental Complete — #{booking_id}", _base_template("Rental Completed", body))


def send_booking_cancelled(
    to: str | list[str],
    client_name: str,
    booking_id: int,
    vehicle: str,
):
    body = f"""
    <p>Dear {client_name},</p>
    <p>Booking <strong>#{booking_id}</strong> has been <span class="badge badge-red">Cancelled</span>.</p>
    <table class="detail-table">
        <tr><td>Booking ID</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
    </table>
    <p>If you have any questions, please contact your rental company directly.</p>
    """
    return _send(to, f"Booking #{booking_id} Cancelled", _base_template("Booking Cancelled", body))


# ---------------------------------------------------------------------------
# Invoice & payment emails
# ---------------------------------------------------------------------------

def send_invoice_notification(
    to: str,
    company_name: str,
    invoice_number: str,
    amount_due: str,
    currency: str,
    due_date: str,
):
    body = f"""
    <p>Dear {company_name},</p>
    <p>A new invoice has been issued for your Rental Manager subscription.</p>
    <table class="detail-table">
        <tr><td>Invoice No.</td><td>{invoice_number}</td></tr>
        <tr><td>Amount due</td><td>{currency} {amount_due}</td></tr>
        <tr><td>Due date</td><td>{due_date}</td></tr>
    </table>
    <p>Please log in to your portal to view and pay this invoice.</p>
    """
    return _send(to, f"Invoice {invoice_number} — Payment Due", _base_template("Invoice Issued", body))


def send_payment_received(
    to: str,
    company_name: str,
    invoice_number: str,
    amount_paid: str,
    currency: str,
):
    body = f"""
    <p>Dear {company_name},</p>
    <p>We have received your payment. Thank you!</p>
    <table class="detail-table">
        <tr><td>Invoice No.</td><td>{invoice_number}</td></tr>
        <tr><td>Amount paid</td><td>{currency} {amount_paid}</td></tr>
        <tr><td>Status</td><td><span class="badge badge-green">Paid</span></td></tr>
    </table>
    """
    return _send(to, f"Payment Received — {invoice_number}", _base_template("Payment Received", body))


# ---------------------------------------------------------------------------
# Subscription emails
# ---------------------------------------------------------------------------

def send_trial_ending_warning(
    to: str,
    company_name: str,
    days_left: int,
    trial_ends_at: str,
):
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your free trial ends in <strong>{days_left} day(s)</strong> on <strong>{trial_ends_at}</strong>.</p>
    <p>To continue using Rental Manager without interruption, please choose a plan and settle your invoice before the trial ends.</p>
    <table class="detail-table">
        <tr><td>Days remaining</td><td>{days_left}</td></tr>
        <tr><td>Trial ends</td><td>{trial_ends_at}</td></tr>
    </table>
    <p>After your trial, your account will move to a 14-day starter trial before being suspended if no plan is selected.</p>
    """
    return _send(to, "Your Trial Is Ending Soon", _base_template("Trial Ending Soon", body))


def send_subscription_past_due(
    to: str,
    company_name: str,
    grace_period_ends_at: str,
):
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your Rental Manager subscription is <span class="badge badge-amber">Past Due</span>.</p>
    <p>You have until <strong>{grace_period_ends_at}</strong> to settle your invoice before your account is suspended.</p>
    <p>During this grace period you can still view your data but cannot add new clients, vehicles, or bookings.</p>
    <p>Please log in to your portal and pay your outstanding invoice to restore full access.</p>
    """
    return _send(to, "Action Required — Subscription Past Due", _base_template("Subscription Past Due", body))


def send_subscription_suspended(
    to: str,
    company_name: str,
):
    body = f"""
    <p>Dear {company_name},</p>
    <p>Your Rental Manager account has been <span class="badge badge-red">Suspended</span> due to non-payment.</p>
    <p>You can still log in and view your existing data, but you cannot add or modify records until your invoice is settled.</p>
    <p>Please contact support or log in to pay your outstanding invoice to reactivate your account.</p>
    """
    return _send(to, "Account Suspended — Action Required", _base_template("Account Suspended", body))


# ---------------------------------------------------------------------------
# User emails
# ---------------------------------------------------------------------------

def send_welcome_email(
    to: str,
    full_name: str,
    role: str,
    temp_password: str,
):
    body = f"""
    <p>Dear {full_name},</p>
    <p>Welcome to Rental Manager! Your account has been created.</p>
    <table class="detail-table">
        <tr><td>Email</td><td>{to}</td></tr>
        <tr><td>Role</td><td>{role.replace("_", " ").title()}</td></tr>
        <tr><td>Temporary password</td><td><strong>{temp_password}</strong></td></tr>
    </table>
    <p>Please log in and change your password immediately.</p>
    """
    return _send(to, "Welcome to Rental Manager", _base_template("Welcome!", body))


def send_password_changed(
    to: str,
    full_name: str,
):
    body = f"""
    <p>Dear {full_name},</p>
    <p>Your Rental Manager password was recently changed.</p>
    <p>If you did not make this change, please contact your administrator immediately.</p>
    """
    return _send(to, "Password Changed", _base_template("Password Changed", body))


def send_password_reset_email(
    to: str,
    full_name: str,
    reset_link: str,
):
    body = f"""
    <p>Dear {full_name},</p>
    <p>We received a request to reset your Rental Manager password.</p>
    <p>Click the button below to set a new password. This link expires in <strong>15 minutes</strong>.</p>
    <a href="{reset_link}" class="btn">Reset my password</a>
    <p style="margin-top: 24px; font-size: 13px; color: #888888;">
        If you did not request a password reset, you can safely ignore this email.
        Your password will not change.
    </p>
    <p style="font-size: 13px; color: #888888;">
        Or copy this link into your browser:<br>
        <span style="color: #4f8cff;">{reset_link}</span>
    </p>
    """
    return _send(
        to,
        "Reset your Rental Manager password",
        _base_template("Password Reset Request", body),
    )


def send_password_reset_success(
    to: str,
    full_name: str,
):
    body = f"""
    <p>Dear {full_name},</p>
    <p>Your Rental Manager password has been successfully reset.</p>
    <p>If you did not make this change, please contact your administrator immediately.</p>
    """
    return _send(
        to,
        "Your password has been reset",
        _base_template("Password Reset Successful", body),
    )


# ---------------------------------------------------------------------------
# Contract emails
# ---------------------------------------------------------------------------

def send_contract_to_client(
    to: str,
    client_name: str,
    contract_number: str,
    vehicle: str,
    start_date: str,
    end_date: str,
    total_amount: str,
    currency: str,
    contract_url: str,
):
    """Send contract signing link to client"""
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental contract is ready for review and signature.</p>
    <table class="detail-table">
        <tr><td>Contract Number</td><td>{contract_number}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Rental Period</td><td>{start_date} to {end_date}</td></tr>
        <tr><td>Total Amount</td><td>{currency} {total_amount}</td></tr>
    </table>
    <p>Please review the contract and sign it electronically by clicking the button below:</p>
    <a href="{contract_url}" class="btn">Review & Sign Contract</a>
    <p style="margin-top: 24px; font-size: 13px; color: #888888;">
        This link will expire in 30 days. If you have any questions, please contact us directly.
    </p>
    """
    return _send(
        to, 
        f"Your Rental Contract - {contract_number}", 
        _base_template("Contract Ready for Signature", body)
    )
