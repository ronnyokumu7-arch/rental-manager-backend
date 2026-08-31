# This file allows you to import functions directly from the package
# e.g., from app.services.email import send_welcome_email

from .auth import (
    send_welcome_email,
    send_password_reset_email,
    send_password_changed,
    send_password_reset_success,
    send_verification_email,
)

from .bookings import (
    send_booking_confirmation,
    send_booking_confirmed,
    send_booking_activated,
    send_booking_completed,
    send_booking_cancelled,
)

from .billing import (
    send_invoice_notification,
    send_payment_received,
    send_trial_ending_warning,
    send_subscription_past_due,
    send_subscription_suspended,
)

from .contracts import (
    send_contract_to_client,
    send_invoice_to_client,
    send_quotation_to_client,
)

__all__ = [
    # Auth
    "send_welcome_email",
    "send_password_reset_email",
    "send_password_changed",
    "send_password_reset_success",
    "send_verification_email",
    # Bookings
    "send_booking_confirmation",
    "send_booking_confirmed",
    "send_booking_activated",
    "send_booking_completed",
    "send_booking_cancelled",
    # Billing
    "send_invoice_notification",
    "send_payment_received",
    "send_trial_ending_warning",
    "send_subscription_past_due",
    "send_subscription_suspended",
    # Contracts
    "send_contract_to_client",
    "send_invoice_to_client",
    "send_quotation_to_client",
]
