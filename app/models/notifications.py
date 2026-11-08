import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Text, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin

if TYPE_CHECKING:
    from app.models.tenants import Tenant
    from app.models.users import User


class NotificationType(str, enum.Enum):
    """
    Categories of notifications. 
    Used by the frontend to determine icons and styling.
    """
    booking = "booking"
    payment = "payment"
    client = "client"
    vehicle = "vehicle"
    system = "system"
    alert = "alert"


class NotificationPriority(str, enum.Enum):
    """
    Urgency level. 'high' priority notifications might trigger push notifications 
    or distinct styling in the dropdown.
    """
    low = "low"
    normal = "normal"
    high = "high"


class Notification(Base, AuditMixin):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    # ========================================================================
    # MULTI-TENANCY & OWNERSHIP
    # ========================================================================
    # tenant_id is required. Even system notifications belong to a tenant context 
    # (or a specific 'platform' tenant if you have one) to ensure strict isolation.
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # ========================================================================
    # CONTENT
    # ========================================================================
    type = Column(Enum(NotificationType), nullable=False, index=True)
    priority = Column(
        Enum(NotificationPriority), 
        nullable=False, 
        default=NotificationPriority.normal, 
        server_default=NotificationPriority.normal.value
    )
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    
    # JSONB allows flexible data (e.g., {"booking_id": 123, "amount": 5000}) 
    # without needing to alter the schema for every new notification type.
    metadata = Column(JSONB, nullable=True, server_default=text("'{}'::jsonb"), default=dict)

    # ========================================================================
    # ACTION & STATE
    # ========================================================================
    # Deep link for the frontend router (e.g., /dashboard/bookings/123)
    action_url = Column(String(500), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False, server_default="false")

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    # Note: We omit 'back_populates' here for now to avoid breaking your current 
    # User/Tenant models. We will add the reverse relationships in a later step.
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    user = relationship("User", foreign_keys=[user_id])

    # ========================================================================
    # INDEXES
    # ========================================================================
    __table_args__ = (
        # CRITICAL: This index makes fetching "Unread Count" and "Recent Unread" 
        # extremely fast (Index Only Scan) without scanning the whole table.
        Index("ix_notifications_user_unread", "user_id", "is_read", "created_at"),
        Index("ix_notifications_tenant_type", "tenant_id", "type", "created_at"),
    )
