"""
Application exception classes — the RAISE side of the error system.

✅ DESIGN:
- Each class owns its status code, default title, default message, default action.
- Raise sites override only what's contextual (message, title, field_errors).
- AppException subclasses HTTPException and embeds the StandardResponse dict
  in `detail` → the existing http_exception_handler shapes it automatically.
  No new handler registration needed.

✅ USAGE:
    from app.core.errors import NotFoundError, ConflictError, ValidationFailedError

    raise NotFoundError(
        title="Booking Not Found",
        message="This booking may have been deleted or the link is wrong.",
    )

    raise ConflictError(
        title="Vehicle Already Booked",
        message="KDJ 720M is already booked for those dates. Pick another vehicle or dates.",
    )
"""
from typing import Optional, Any

from fastapi import HTTPException, status

from app.schemas.standard_response import (
    StandardResponse,
    ActionButton,
    retry_action,
    navigate_action,
)


class AppException(HTTPException):
    """
    Base class for all application errors.

    Carries a StandardResponse as `detail` so the global http_exception_handler
    returns it verbatim (spread-then-layer keeps every field top-level).
    """
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_title: str = "Request Failed"
    default_message: str = "Something went wrong with this request."
    default_action: Optional[ActionButton] = None

    def __init__(
        self,
        message: Optional[str] = None,
        title: Optional[str] = None,
        action: Optional[ActionButton] = None,
        field_errors: Optional[dict[str, str]] = None,
        details: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        self.response = StandardResponse(
            type="error",
            title=title or self.default_title,
            message=message or self.default_message,
            action=action if action is not None else self.default_action,
            field_errors=field_errors,
            details=details,
        )
        super().__init__(
            status_code=self.status_code,
            detail=self.response.model_dump(exclude_none=True),
            headers=headers,
        )


# ═══════════════════════════════════════════════════════════════
# ✅ CONCRETE ERRORS — one per HTTP semantics
# ═══════════════════════════════════════════════════════════════

class BadRequestError(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_title = "Request Failed"
    default_message = "We couldn't process this request. Please check your input."


class AuthenticationError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_title = "Session Expired"
    default_message = "Your session has expired. Please log in again to continue."
    default_action = navigate_action("Log In", "/login")


class AuthorizationError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    default_title = "Permission Denied"
    default_message = "You don't have permission to perform this action."


class PaymentRequiredError(AppException):
    """HTTP 402 — an account-level payment action is required."""
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_title = "Payment Required"
    default_message = "A payment is required before you can continue."
    default_action = navigate_action("Make Payment", "/commission/pay")


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    default_title = "Not Found"
    default_message = "The item you're looking for doesn't exist or may have been removed."
    default_action = navigate_action("Go Home", "/dashboard")


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    default_title = "Conflict"
    default_message = "This action conflicts with existing data. Please review and adjust."


class ValidationFailedError(AppException):
    """422 with field-level errors for form highlighting."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_title = "Validation Failed"
    default_message = "Please fix the highlighted fields and try again."
    default_action = ActionButton(label="Fix Issues", action="dismiss")


class RateLimitedError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_title = "Too Many Requests"
    default_message = "You're doing that too quickly. Please wait a moment and try again."
    default_action = retry_action()


class PayloadTooLargeError(AppException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_title = "File Too Large"
    default_message = "This file is too large to upload."


class ServerError(AppException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_title = "Server Error"
    default_message = "Something went wrong on our end. Please try again."
    default_action = retry_action()


class GoneError(AppException):
    """410 Gone — links that were valid but are now dead (used/expired invites)."""
    status_code = status.HTTP_410_GONE
    default_title = "Link No Longer Valid"
    default_message = "This link has expired or was already used."
    default_action = retry_action()


class UnprocessableEntityError(AppException):
    """HTTP 422 Unprocessable Entity - Validation failed."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
