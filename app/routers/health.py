from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["System"])

@router.get("/health")
async def system_health_check():
    """
    Lightweight system health check for Render monitoring.
    Returns 200 OK immediately - no database queries, no auth required.
    Render uses this to verify the service is alive.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "rental-manager-api",
            "version": "1.0.0"
        }
    )

@router.head("/health")
async def system_health_check_head():
    """
    HEAD request for health check (Render uses HEAD for monitoring).
    Returns 200 OK with no body.
    """
    return JSONResponse(status_code=200)
