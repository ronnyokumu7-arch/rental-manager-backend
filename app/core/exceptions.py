"""
Global exception handlers for FastAPI.
Transforms all exceptions into structured StandardResponse envelopes.

✅ DESIGN:
- Backend owns all error content (titles, messages, actions)
- Frontend only displays
- Backward compatible during migration (old format still works)
- Structured actions help users resolve issues

✅ MIGRATION STRATEGY (dict business errors):
"Spread-then-layer" — ALL legacy/business keys (upgrade_url, retry_after,
business codes, error flags) are preserved at the TOP level so existing
frontend logic keeps working, and the new StandardResponse fields
(type / title / message / action) are layered on top.
"""
import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException, RequestValidationError
from pydantic import ValidationError

from app.schemas.standard_response import (
    StandardResponse,
    ActionButton,
)
from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")


# ═══════════════════════════════════════════════════════════════
# ✅ HELPERS
# ═══════════════════════════════════════════════════════════════

def _get_status_title(status_code: int) -> str:
    """Map HTTP status codes to user-friendly titles."""
    title_map = {
        400: "Request Failed",
        401: "Session Expired",
        403: "Permission Denied",
        404: "Not Found",
        409: "Conflict",
        422: "Validation Failed",
        429: "Rate Limited",
        500: "Server Error",
        502: "Service Unavailable",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return title_map.get(status_code, "Error")


def _get_default_action(status_code: int) -> ActionButton | None:
    """Provide default recovery actions based on error type."""
    if status_code == 401:
        return ActionButton(label="Log In", href="/login", action="navigate")
    elif status_code == 404:
        return ActionButton(label="Go Home", href="/dashboard", action="navigate")
    elif status_code == 429:
        return ActionButton(label="Retry", action="retry")
    elif status_code in (500, 502, 503, 504):
        return ActionButton(label="Retry", action="retry")
    return None


def _clean_pydantic_msg(msg: str) -> str:
    """Turn verbose Pydantic messages into human copy."""
    if msg.startswith("Value error, "):
        return msg.replace("Value error, ", "")
    if msg.startswith("Input should be "):
        return msg.replace("Input should be ", "Must be ")
    if msg == "Field required":
        return "This field is required"
    if msg.startswith("String should have at most"):
        return "Value is too long"
    if msg.startswith("String should have at least"):
        return "Value is too short"
    if msg.startswith("Input should be a valid"):
        return "Invalid value"
    return msg


def _field_name_from_loc(loc: tuple | list) -> str:
    """Build a clean field path, dropping the 'body' prefix."""
    parts = [str(part) for part in loc]
    if parts and parts[0] == "body":
        parts = parts[1:]
    return ".".join(parts) if parts else "unknown"


# ═══════════════════════════════════════════════════════════════
# ✅ HANDLERS
# ═══════════════════════════════════════════════════════════════

async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handles FastAPI HTTPException with structured StandardResponse envelope.

    Supports:
    - Plain string details  → type/title/message + default action
    - Dict details          → spread-then-layer (legacy keys preserved)
    - List details          → grouped under details.errors
    - Preserves headers (e.g., WWW-Authenticate for 401)
    """
    status_code = exc.status_code

    if isinstance(exc.detail, dict):
        # ✅ SPREAD-THEN-LAYER: every legacy/business key stays top-level
        # (upgrade_url, retry_after, error flag, business codes) so existing
        # frontend logic keeps working; new fields layered on top.
        response_data: dict[str, Any] = dict(exc.detail)

        response_data.setdefault("type", "error")
        response_data.setdefault("title", _get_status_title(status_code))

        if "message" not in response_data:
            # Promote legacy field name, else default copy
            response_data["message"] = response_data.pop("error_message", "An error occurred")

        if "action" not in response_data:
            default_action = _get_default_action(status_code)
            if default_action:
                response_data["action"] = default_action.model_dump(exclude_none=True)

    elif isinstance(exc.detail, list):
        # List of errors (rare, but handle gracefully)
        response_data = StandardResponse(
            type="error",
            title="Multiple Errors",
            message="Multiple issues were found. Please review and fix them.",
            details={"errors": exc.detail},
        ).model_dump(exclude_none=True)

    else:
        # Plain string detail
        response_data = StandardResponse(
            type="error",
            title=_get_status_title(status_code),
            message=str(exc.detail),
            action=_get_default_action(status_code),
        ).model_dump(exclude_none=True)

    # Preserve headers (critical for 401 WWW-Authenticate)
    headers = getattr(exc, "headers", None)

    return JSONResponse(
        status_code=status_code,
        content=response_data,
        headers=headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handles Pydantic request validation errors.
    Returns 422 with structured field_errors for frontend form handling.
    """
    field_errors: dict[str, str] = {}

    for error in exc.errors():
        field_name = _field_name_from_loc(error.get("loc", []))
        msg = _clean_pydantic_msg(error.get("msg", "Invalid value"))

        # First error per field wins (most specific)
        if field_name not in field_errors:
            field_errors[field_name] = msg

    response_data = StandardResponse(
        type="error",
        title="Validation Failed",
        message="Please fix the highlighted fields and try again.",
        field_errors=field_errors,
        action=ActionButton(label="Fix Issues", action="dismiss"),
    ).model_dump(exclude_none=True)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_data,
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for unhandled exceptions.

    ✅ SECURITY:
    - Logs full error with stack trace for backend debugging
    - Returns sanitized response to client (NEVER leaks stack traces,
      internal paths, or tenant data)
    - In debug mode, includes error type for faster development iteration
    """
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
        extra={"path": str(request.url.path), "method": request.method},
    )

    settings = get_settings()

    if settings.debug:
        message = f"{type(exc).__name__}: {str(exc)}"
        details = {"error_type": type(exc).__name__, "error_message": str(exc)}
    else:
        message = "Something went wrong on our end. Please try again."
        details = None

    response_data = StandardResponse(
        type="error",
        title="Server Error",
        message=message,
        action=ActionButton(label="Retry", action="retry"),
        details=details,
    ).model_dump(exclude_none=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response_data,
    )


async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """
    Handles Pydantic ValidationError raised OUTSIDE request validation
    (e.g., model construction in services). Converts to field_errors.
    """
    field_errors: dict[str, str] = {}

    for error in exc.errors():
        field_name = _field_name_from_loc(error.get("loc", ()))
        msg = _clean_pydantic_msg(error.get("msg", "Invalid value"))

        if field_name not in field_errors:
            field_errors[field_name] = msg

    response_data = StandardResponse(
        type="error",
        title="Validation Failed",
        message="Please fix the highlighted fields and try again.",
        field_errors=field_errors,
        action=ActionButton(label="Fix Issues", action="dismiss"),
    ).model_dump(exclude_none=True)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_data,
    )
