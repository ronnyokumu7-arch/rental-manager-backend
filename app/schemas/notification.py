from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, ConfigDict

from app.models.notifications import NotificationType, NotificationPriority


# ============================================================================
# BASE SCHEMAS
# ============================================================================

class NotificationBase(BaseModel):
    """Shared attributes for notifications."""
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.normal
    title: str
    message: str
    metadata: Optional[Dict[str, Any]] = None
    action_url: Optional[str] = None
    is_read: bool = False


class NotificationCreate(NotificationBase):
    """
    Schema used internally by the NotificationService to create a record.
    tenant_id and user_id are injected by the service, not the API caller.
    """
    tenant_id: int
    user_id: int


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class NotificationOut(NotificationBase):
    """
    Standard API response model for a single notification.
    """
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """
    Paginated response for the notification list endpoint.
    """
    items: List[NotificationOut]
    total: int
    page: int
    per_page: int
    has_more: bool


class NotificationCountResponse(BaseModel):
    """
    Lightweight response for the unread badge count.
    This is designed to be cached in Redis for maximum performance.
    """
    unread_count: int
    total_count: int
