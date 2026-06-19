from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException

async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Standardizes the error response format for all HTTPExceptions.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "code": exc.status_code,
            "message": exc.detail
        },
    )