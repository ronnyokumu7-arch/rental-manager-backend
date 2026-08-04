import enum
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class VehicleStatus(str, enum.Enum):
    pending_activation = "pending_activation"
    available = "available"
    rented = "rented"
    maintenance = "maintenance"
    awaiting_mileage = "awaiting_mileage"
    retired = "retired"

class Vehicle(Base, AuditMixin):
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # Core Identity (with bounded lengths for DB safety)
    make = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    plate_number = Column(String(50), nullable=False)
    vin = Column(String(50), nullable=True)  # Standard VIN is 17, 50 allows for edge cases
    
    status = Column(
        Enum(VehicleStatus),
        nullable=False,
        default=VehicleStatus.pending_activation,
        server_default=VehicleStatus.pending_activation.value,
    )
    
    # Financial & Operational Metrics
    daily_rate = Column(Numeric(10, 2), nullable=False)
    current_mileage = Column(Integer, nullable=False, default=0, server_default="0")
    next_service_km = Column(Integer, nullable=True)
    
    # Compliance & Documentation (URLs bounded to 500 chars)
    insurance_number = Column(String(100), nullable=True)
    insurance_expiry = Column(DateTime(timezone=True), nullable=True)
    insurance_doc = Column(String(500), nullable=True)
    registration_doc = Column(String(500), nullable=True)
    inspection_doc = Column(String(500), nullable=True)
    
    # Lifecycle & Metadata
    notes = Column(Text, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity
    tenant = relationship("Tenant", back_populates="vehicles", foreign_keys=[tenant_id])
    
    # ✅ CRITICAL FIX: Removed 'delete-orphan'. 
    # Historical bookings must be preserved for financial/audit records even if a vehicle is archived/deleted.
    bookings = relationship("Booking", back_populates="vehicle")

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # 1. Unique constraints for duplicate prevention
        UniqueConstraint("tenant_id", "plate_number", name="uq_tenant_plate"),
        UniqueConstraint("tenant_id", "vin", name="uq_tenant_vin"),
        
        # 2. Data Integrity Check Constraints
        CheckConstraint("year >= 1900", name="ck_vehicles_year_valid"),
        CheckConstraint("current_mileage >= 0", name="ck_vehicles_mileage_non_negative"),
        
        # 3. Main Vehicle List View (MOST IMPORTANT)
        # Query: WHERE tenant_id = ? AND is_archived = false ORDER BY created_at DESC
        Index("ix_vehicles_tenant_archived_created", "tenant_id", "is_archived", "created_at"),
        
        # 4. Archived Vehicles List View
        # Query: WHERE tenant_id = ? AND is_archived = true ORDER BY archived_at DESC
        Index("ix_vehicles_tenant_archived_date", "tenant_id", "is_archived", "archived_at"),
        
        # 5. Status Filtering (for fleet management)
        # Query: WHERE tenant_id = ? AND status = ?
        Index("ix_vehicles_tenant_status", "tenant_id", "status"),
        
        # 6. Insurance Expiry Checks (CRITICAL for daily scheduler)
        # Query: WHERE tenant_id = ? AND insurance_expiry IS NOT NULL AND insurance_expiry < ?
        Index("ix_vehicles_tenant_insurance_expiry", "tenant_id", "insurance_expiry"),
        
        # 7. Single Vehicle Lookup with Tenant Scoping
        # Query: WHERE tenant_id = ? AND id = ?
        Index("ix_vehicles_tenant_id", "tenant_id", "id"),
    )
