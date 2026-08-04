import enum
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class ClientStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    inactive = "inactive"
    suspended = "suspended"

class Client(Base, AuditMixin):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # Core Identity (with bounded lengths for DB safety)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=False, index=True)
    id_number = Column(String(50), nullable=True)
    dl_number = Column(String(50), nullable=True)
    dl_expiry = Column(Date, nullable=True)
    
    status = Column(
        Enum(ClientStatus),
        nullable=False, 
        default=ClientStatus.pending,
        server_default=ClientStatus.pending.value,
    )
    
    # Addresses
    residential_address = Column(Text, nullable=True)
    work_address = Column(Text, nullable=True)
    
    # Compliance Documents (URLs bounded to 500 chars)
    id_image_front = Column(String(500), nullable=True)
    id_image_back = Column(String(500), nullable=True)
    dl_image_front = Column(String(500), nullable=True)
    avatar_image = Column(String(500), nullable=True)
    
    # Emergency Contact
    next_of_kin_name = Column(String(255), nullable=True)
    next_of_kin_phone = Column(String(50), nullable=True)
    
    # Lifecycle & Metadata
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    tenant = relationship("Tenant", back_populates="clients")
    
    # ✅ CRITICAL FIX: Removed 'delete-orphan'. 
    # Historical bookings must be preserved for financial/audit records even if a client is archived/deleted.
    bookings = relationship("Booking", back_populates="client")

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # 1. Unique constraints for duplicate prevention
        UniqueConstraint("tenant_id", "phone", name="uq_tenant_phone"),
        UniqueConstraint("tenant_id", "id_number", name="uq_tenant_id_number"),
        
        # 2. Main client list view (MOST IMPORTANT)
        # Query: WHERE tenant_id = ? AND is_archived = false ORDER BY created_at DESC
        Index("ix_clients_tenant_archived_created", "tenant_id", "is_archived", "created_at"),
        
        # 3. Archived clients list view
        # Query: WHERE tenant_id = ? AND is_archived = true ORDER BY archived_at DESC
        Index("ix_clients_tenant_archived_date", "tenant_id", "is_archived", "archived_at"),
        
        # 4. Status filtering (for compliance checks)
        # Query: WHERE tenant_id = ? AND status = ?
        Index("ix_clients_tenant_status", "tenant_id", "status"),
    )
