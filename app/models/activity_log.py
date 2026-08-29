from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Index, Text
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class ActivityLog(Base, AuditMixin):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    
    # ✅ CRITICAL: tenant_id for multi-tenancy isolation (Never exposed without tenant check)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # ✅ Changed to SET NULL for audit preservation
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # ✅ Bounded strings to prevent DB bloat
    action = Column(String(100), nullable=False)  # e.g., "payment_received", "trip_overdue"
    
    # ✅ NEW: Human-readable label for immediate UI rendering (avoids frontend mapping errors)
    label = Column(String(255), nullable=False, default="Activity")  # e.g., "Payment Received", "Trip Overdue"
    
    # ✅ Bounded target types
    target_type = Column(String(50), nullable=True)  # e.g., "booking", "invoice", "client", "vehicle", "driver"
    target_id = Column(Integer, nullable=True)
    
    # ✅ NEW: Denormalized summary for instant feed rendering
    # Example: {"client_name": "John Doe", "client_phone": "0712345678", "amount": "KES 11,000", "ref": "QWERTYPA01"}
    summary = Column(JSON, nullable=True)
    
    # ✅ Detailed JSON details for flexible metadata storage
    details = Column(JSON, nullable=True)
    
    # ✅ NEW: Priority level for the Dashboard feed
    # 1 = Low, 2 = Normal, 3 = High (e.g., Invoice Overdue, Trip Overdue), 4 = Critical (e.g., DL Expired)
    priority = Column(Integer, nullable=False, default=2)
    
    # ✅ NEW: Full-text search vector for future Logs CRUD (PostgreSQL only)
    # search_vector = Column(TSVECTOR, nullable=True) # Uncomment if using PostgreSQL
    
    # Relationships
    user = relationship("User", back_populates="activity_logs", foreign_keys=[user_id])
    tenant = relationship("Tenant", back_populates="activity_logs", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES:
    __table_args__ = (
        # 1. User Activity Feed (MOST IMPORTANT)
        Index("ix_activity_logs_tenant_user_created", "tenant_id", "user_id", "created_at"),
        
        # 2. Tenant-Wide Activity Feed (for admin dashboards)
        Index("ix_activity_logs_tenant_created", "tenant_id", "created_at"),
        
        # 3. Action Type Filtering (for audit reports)
        Index("ix_activity_logs_tenant_action", "tenant_id", "action", "created_at"),
        
        # 4. Target Resource Lookup
        Index("ix_activity_logs_target", "tenant_id", "target_type", "target_id", "created_at"),
        
        # 5. NEW: Dashboard Priority Filter (for showing critical items first)
        Index("ix_activity_logs_tenant_priority_created", "tenant_id", "priority", "created_at"),
    )

    def __repr__(self):
        return f"<ActivityLog id={self.id} action={self.action} tenant_id={self.tenant_id}>"
