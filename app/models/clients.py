import enum
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class ClientStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    inactive = "inactive"
    suspended = "suspended"

class IdType(str, enum.Enum):
    """✅ IDENTITY SLOT: which document `id_number` currently holds."""
    national_id = "national_id"
    passport = "passport"

class Client(Base, AuditMixin):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # Core Identity (with bounded lengths for DB safety)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=False, index=True)

    # ✅ IDENTITY SLOT: id_type + id_number = ONE display slot, no null states.
    # Existing rows backfill to national_id via server_default.
    # App-level schemas enforce "must pick one" for NEW onboarding.
    id_type = Column(
        Enum(IdType),
        nullable=False,
        default=IdType.national_id,
        server_default=IdType.national_id.value,
    )
    id_number = Column(String(50), nullable=True)  # value of the selected document

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
    
    # Emergency Contact (✅ exempt from uniqueness; feeds F1/F2 risk flags)
    next_of_kin_name = Column(String(255), nullable=True)
    next_of_kin_phone = Column(String(50), nullable=True)

    # ✅ RISK FLAGS: soft suspicion markers for due diligence before activation.
    # (v2 graduates this to a JSONB risk_flags array for the vetting engine)
    is_flagged = Column(Boolean, nullable=False, default=False, server_default="false")
    flag_notes = Column(Text, nullable=True)

    # Lifecycle & Metadata
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="clients")
    bookings = relationship("Booking", back_populates="client")

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # 1. Hard-block uniqueness (per tenant). NULLs stay distinct in Postgres.
        UniqueConstraint("tenant_id", "phone", name="uq_tenant_phone"),
        # ✅ IDENTITY SLOT: type-aware uniqueness (replaces uq_tenant_id_number)
        UniqueConstraint("tenant_id", "id_type", "id_number", name="uq_tenant_id_slot"),
        # ✅ NEW: email + DL per-tenant uniqueness
        UniqueConstraint("tenant_id", "email", name="uq_tenant_email"),
        UniqueConstraint("tenant_id", "dl_number", name="uq_tenant_dl_number"),
        
        # 2. Main client list view (MOST IMPORTANT)
        Index("ix_clients_tenant_archived_created", "tenant_id", "is_archived", "created_at"),
        
        # 3. Archived clients list view
        Index("ix_clients_tenant_archived_date", "tenant_id", "is_archived", "archived_at"),
        
        # 4. Status filtering (compliance checks + pending review queue)
        Index("ix_clients_tenant_status", "tenant_id", "status"),
    )
