"""
Standard response schema for all API endpoints.
Backend owns content + logic; frontend only displays.

✅ USAGE IN ROUTERS:
    from app.schemas.standard_response import success, error, retry_action

    return success(
        title="Booking Created",
        message="Your booking is confirmed. A quotation has been sent to the client.",
        action=navigate_action("View Booking", f"/dashboard/bookings/{booking.id}"),
    )

    raise ConflictError(...)  # or return error(...) for non-exception flows
"""
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field


class ActionButton(BaseModel):
    """Actionable button to help user resolve issues or continue a flow."""
    label: str = Field(..., description="Button text, e.g., 'Retry', 'View Booking'")
    href: Optional[str] = Field(None, description="Navigation path, e.g., '/dashboard'")
    action: Literal["retry", "navigate", "dismiss", "reload"] = Field(
        "dismiss",
        description="Client-side behavior: retry request, navigate, dismiss toast, reload page",
    )


class StandardResponse(BaseModel):
    """
    Structured response for all API interactions.

    ✅ DESIGN PRINCIPLES:
    - Backend owns all content (no frontend string concatenation)
    - Actionable: tells users what to do, not just what failed
    - Field-level errors for forms
    - Toast-ready: frontend only displays
    """
    type: Literal["error", "success", "warning", "info"] = Field(..., description="Message severity")
    title: str = Field(..., description="Short headline, e.g., 'Booking Failed'")
    message: str = Field(..., description="User-facing explanation")
    action: Optional[ActionButton] = Field(None, description="Optional action button")
    field_errors: Optional[dict[str, str]] = Field(
        None,
        description="Field-level errors for forms, e.g., {'email': 'Already registered'}",
    )
    details: Optional[dict[str, Any]] = Field(
        None,
        description="Technical/business extras (debugging + legacy keys; never rendered as copy)",
    )

    def to_dict(self) -> dict:
        """JSON-ready dict without None fields."""
        return self.model_dump(exclude_none=True)


class SuccessResponse(StandardResponse):
    """Success response with type='success' pre-set."""
    type: Literal["success"] = "success"


class ErrorResponse(StandardResponse):
    """Error response with type='error' pre-set."""
    type: Literal["error"] = "error"


class WarningResponse(StandardResponse):
    """Warning response with type='warning' pre-set."""
    type: Literal["warning"] = "warning"


class InfoResponse(StandardResponse):
    """Info response with type='info' pre-set."""
    type: Literal["info"] = "info"


# ═══════════════════════════════════════════════════════════════
# ✅ ACTION PRESETS — common buttons, one-liners in routers
# ═══════════════════════════════════════════════════════════════

def retry_action(label: str = "Retry") -> ActionButton:
    return ActionButton(label=label, action="retry")


def navigate_action(label: str, href: str) -> ActionButton:
    return ActionButton(label=label, href=href, action="navigate")


def reload_action(label: str = "Reload Page") -> ActionButton:
    return ActionButton(label=label, action="reload")


# ═══════════════════════════════════════════════════════════════
# ✅ FACTORY HELPERS — keep router code to one expression
# ═══════════════════════════════════════════════════════════════

def success(
    title: str,
    message: str,
    action: Optional[ActionButton] = None,
    details: Optional[dict[str, Any]] = None,
) -> SuccessResponse:
    return SuccessResponse(title=title, message=message, action=action, details=details)


def error(
    title: str,
    message: str,
    action: Optional[ActionButton] = None,
    field_errors: Optional[dict[str, str]] = None,
    details: Optional[dict[str, Any]] = None,
) -> ErrorResponse:
    return ErrorResponse(
        title=title, message=message, action=action,
        field_errors=field_errors, details=details,
    )


def warning(
    title: str,
    message: str,
    action: Optional[ActionButton] = None,
) -> WarningResponse:
    return WarningResponse(title=title, message=message, action=action)


def info(
    title: str,
    message: str,
    action: Optional[ActionButton] = None,
) -> InfoResponse:
    return InfoResponse(title=title, message=message, action=action)
