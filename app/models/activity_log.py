from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class ActivityLog(Base, AuditMixin):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    
    # ✅ CRITICAL: Added tenant_id for multi-tenancy isolation
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # ✅ Changed to SET NULL for audit preservation (logs survive user deletion)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # ✅ Bounded strings to prevent DB bloat
    action = Column(String(100), nullable=False)  # e.g., "create_booking", "void_payment"
    target_type = Column(String(50), nullable=True)  # e.g., "booking", "invoice", "client"
    target_id = Column(Integer, nullable=True)
    
    # JSON details for flexible metadata storage
    details = Column(JSON, nullable=True) 
    
    # ✅ Timestamp removed: created_at is now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve ambiguity with AuditMixin.created_by
    user = relationship("User", back_populates="activity_logs", foreign_keys=[user_id])
    tenant = relationship("Tenant", back_populates="activity_logs", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES:
    __table_args__ = (
        # 1. User Activity Feed (MOST IMPORTANT)
        # Query: WHERE tenant_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?
        Index("ix_activity_logs_tenant_user_created", "tenant_id", "user_id", "created_at"),
        
        # 2. Tenant-Wide Activity Feed (for admin dashboards)
        # Query: WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?
        Index("ix_activity_logs_tenant_created", "tenant_id", "created_at"),
        
        # 3. Action Type Filtering (for audit reports)
        # Query: WHERE tenant_id = ? AND action = ? ORDER BY created_at DESC
        Index("ix_activity_logs_tenant_action", "tenant_id", "action", "created_at"),
        
        # 4. Target Resource Lookup (e.g., "show all activity for booking #123")
        # Query: WHERE tenant_id = ? AND target_type = ? AND target_id = ? ORDER BY created_at DESC
        Index("ix_activity_logs_target", "tenant_id", "target_type", "target_id", "created_at"),
    )
