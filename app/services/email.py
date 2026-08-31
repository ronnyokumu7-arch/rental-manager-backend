# app/services/email.py
# ✅ ORCHESTRATOR / SHIM: Re-exports everything from the new modular email package.
# This ensures zero breaking changes for existing imports across the app.

from app.services.email.auth import (
    send_welcome_email,
    send_password_reset_email,
    send_password_reset_success,
    send_password_changed,
    send_verification_email,
)
from app.services.email.bookings import (
    send_booking_confirmation,
    send_booking_confirmed,
    send_booking_activated,
    send_booking_completed,
    send_booking_cancelled,
)
from app.services.email.billing import (
    send_invoice_notification,
    send_payment_received,
    send_trial_ending_warning,
    send_subscription_past_due,
    send_subscription_suspended,
)
from app.services.email.contracts import (
    send_contract_to_client,
    send_invoice_to_client,
    send_quotation_to_client,
)
from app.services.email.client import _send

__all__ = [
    "send_welcome_email",
    "send_password_reset_email",
    "send_password_reset_success",
    "send_password_changed",
    "send_verification_email",
    "send_booking_confirmation",
    "send_booking_confirmed",
    "send_booking_activated",
    "send_booking_completed",
    "send_booking_cancelled",
    "send_invoice_notification",
    "send_payment_received",
    "send_trial_ending_warning",
    "send_subscription_past_due",
    "send_subscription_suspended",
    "send_contract_to_client",
    "send_invoice_to_client",
    "send_quotation_to_client",
    "_send",
]
