from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.services.notification import NotificationService
from app.schemas.notification import (
    NotificationListResponse,
    NotificationCountResponse,
    NotificationOut,
    BulkNotificationAction,  # ✅ ADDED
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ─── COUNTS (For the TopBar Badge) ────────────────────────────────────────
@router.get("/counts", response_model=NotificationCountResponse)
@limiter.limit("60/minute")  # Higher limit since the frontend might poll this
async def get_notification_counts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch unread and total notification counts for the current user."""
    return await NotificationService.get_counts(db, current_user.id)


# ─── LIST (For the Dropdown) ─────────────────────────────────────────────
@router.get("/", response_model=NotificationListResponse)
@limiter.limit("30/minute")
async def list_notifications(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    filter: str = "all",  # ✅ UPDATED: Replaced unread_only with filter
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch paginated notifications. Filter can be 'all', 'unread', or 'read'."""
    # Basic validation to ensure only expected values hit the service
    if filter not in ("all", "unread", "read"):
        filter = "all"
        
    return await NotificationService.get_list(
        db, current_user.id, page, per_page, filter
    )


# ─── STATE MANAGEMENT ────────────────────────────────────────────────────
@router.patch("/{notification_id}/read", response_model=NotificationOut)
@limiter.limit("30/minute")
async def mark_notification_as_read(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a specific notification as read."""
    return await NotificationService.mark_as_read(db, current_user.id, notification_id)


@router.patch("/read-all", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def mark_all_notifications_as_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all unread notifications as read. Returns 204 No Content."""
    await NotificationService.mark_all_as_read(db, current_user.id)
    return None


# ─── BULK ACTIONS (For Multi-Select UI) ──────────────────────────────────
@router.post("/bulk-read", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def mark_multiple_as_read(
    request: Request,
    payload: BulkNotificationAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark specific notifications as read."""
    await NotificationService.mark_multiple_as_read(
        db, current_user.id, payload.ids
    )
    return None


@router.post("/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def delete_multiple_notifications(
    request: Request,
    payload: BulkNotificationAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete specific notifications (used for 'Archive' in UI)."""
    await NotificationService.delete_multiple(
        db, current_user.id, payload.ids
    )
    return None


# ─── CLEANUP ─────────────────────────────────────────────────────────────
@router.post("/clear-read", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def clear_read_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually delete all read notifications for the current user.
    Used by the "Clear read" button in the UI to keep the inbox clean.
    """
    await NotificationService.clear_read_notifications(db, current_user.id)
    return None
