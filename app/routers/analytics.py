// app/routers/analytics.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.post("/track-pageview")
async def track_pageview(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Track page visits for custom analytics.
    Called from frontend on route changes.
    """
    data = await request.json()
    
    # Extract visitor info
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")
    
    # Store in database
    pageview = PageView(
        path=data["path"],           # "/dashboard/bookings"
        user_id=data.get("user_id"), # null if not logged in
        tenant_id=data.get("tenant_id"),
        ip_address=ip,
        user_agent=user_agent,
        referrer=data.get("referrer"),
        timestamp=datetime.now(timezone.utc)
    )
    
    db.add(pageview)
    await db.commit()
    
    return {"status": "tracked"}
