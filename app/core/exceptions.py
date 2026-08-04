import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException, RequestValidationError

logger = logging.getLogger("uvicorn.error")


async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handles FastAPI HTTPException with consistent error envelope.
    
    Supports:
    - String details: {"error": true, "code": 404, "message": "Not found"}
    - Dict details (business errors): {"error": true, "code": "SUBSCRIPTION_SUSPENDED", "message": "..."}
    - Preserves headers (e.g., WWW-Authenticate for 401)
    """
    response = {
        "error": True,
        "code": exc.status_code,
    }
    
    if isinstance(exc.detail, dict):
        # Structured business error (e.g., subscription errors with business codes)
        # Spread dict into response, preserving business code and message
        response.update(exc.detail)
        response["error"] = True  # Ensure error flag is always present
        if "message" not in response:
            response["message"] = "An error occurred"
    elif isinstance(exc.detail, list):
        # List of errors (rare, but handle gracefully)
        response["message"] = "Multiple errors occurred"
        response["details"] = exc.detail
    else:
        # Plain string detail
        response["message"] = str(exc.detail)
    
    # Preserve headers (critical for 401 WWW-Authenticate)
    headers = getattr(exc, "headers", None)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response,
        headers=headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handles Pydantic validation errors with field-level details.
    Returns 422 with structured error list for frontend form handling.
    """
    errors = []
    for error in exc.errors():
        # Build field path (e.g., "body.email" or "query.page")
        field_path = ".".join(str(loc) for loc in error.get("loc", []) if loc != "body")
        
        errors.append({
            "field": field_path or "unknown",
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        })
    
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "code": 422,
            "message": "Validation failed",
            "details": errors,
        },
    )


async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions.
    
    SECURITY:
    - Logs full error with stack trace for backend debugging
    - Returns sanitized response to client (NEVER leaks stack traces, internal paths, or tenant data)
    - In debug mode, includes error type for faster development iteration
    """
    # Log with full context for backend debugging
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
        extra={"path": str(request.url.path), "method": request.method},
    )
    
    # In development, include error type for faster debugging
    # In production, return generic message to prevent information disclosure
    from app.core.config import get_settings
    settings = get_settings()
    
    if settings.debug:
        message = f"{type(exc).__name__}: {str(exc)}"
    else:
        message = "An internal server error occurred. Please try again later."
    
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "code": 500,
            "message": message,
        },
    )
