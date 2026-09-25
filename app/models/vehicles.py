import enum
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class VehicleStatus(str, enum.Enum):
    """
    ✅ 5-state fleet lifecycle (awaiting_mileage removed — it caused stuck vehicles).

    pending_activation → new vehicle, not yet live (insurance gate)
    available          → ready to rent
    rented             → out with a client (owned ONLY by booking transitions)
    maintenance        → out of service (manual)
    retired            → removed from fleet (manual)
    """
    pending_activation = "pending_activation"
    available = "available"
    rented = "rented"
    maintenance = "maintenance"
    retired = "retired"

class Vehicle(Base, AuditMixin):
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # ✅ NEW: Investor Ownership Link
    # If NULL, the agency owns the car. If set, it belongs to an investor.
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
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
    # ✅ UPDATED: Added default=0 so investor cars can be saved without a daily_rate
    daily_rate = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    current_mileage = Column(Integer, nullable=False, default=0, server_default="0")
    next_service_km = Column(Integer, nullable=True)

    # ✅ MILEAGE TRACKING
    mileage_due = Column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    # ✅ MILESTONE 2: Airport Transfer Support
    supports_airport_transfer = Column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    airport_transfer_base_rate = Column(Numeric(10, 2), nullable=True)

    # ✅ MILESTONE 3: Wedding Car Hire Support
    supports_wedding_service = Column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    wedding_base_rate = Column(Numeric(10, 2), nullable=True)  # 12H package base rate
    
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

    # Relationships
    tenant = relationship("Tenant", back_populates="vehicles", foreign_keys=[tenant_id])
    
    # ✅ NEW: Relationship to the Investor (User)
    owner = relationship("User", foreign_keys=[owner_id])

    bookings = relationship("Booking", back_populates="vehicle")

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # 1. Unique constraints for duplicate prevention
        UniqueConstraint("tenant_id", "plate_number", name="uq_tenant_plate"),
        UniqueConstraint("tenant_id", "vin", name="uq_tenant_vin"),
        
        # 2. Data Integrity Check Constraints
        CheckConstraint("year >= 1900", name="ck_vehicles_year_valid"),
        CheckConstraint("current_mileage >= 0", name="ck_vehicles_mileage_non_negative"),
        
        # 9. Airport Transfer Base Rate Check
        CheckConstraint(
            "(supports_airport_transfer = false) OR (airport_transfer_base_rate > 0)", 
            name="ck_vehicles_airport_transfer_base_rate_non_negative"
        ),

        # 10. Wedding Service Base Rate Check
        CheckConstraint(
            "(supports_wedding_service = false) OR (wedding_base_rate > 0)", 
            name="ck_vehicles_wedding_base_rate_non_negative"
        ),
        
        # 3. Main Vehicle List View
        Index("ix_vehicles_tenant_archived_created", "tenant_id", "is_archived", "created_at"),
        
        # 4. Archived Vehicles List View
        Index("ix_vehicles_tenant_archived_date", "tenant_id", "is_archived", "archived_at"),
        
        # 5. Status Filtering
        Index("ix_vehicles_tenant_status", "tenant_id", "status"),
        
        # 6. Insurance Expiry Checks
        Index("ix_vehicles_tenant_insurance_expiry", "tenant_id", "insurance_expiry"),
        
        # 7. Single Vehicle Lookup
        Index("ix_vehicles_tenant_id", "tenant_id", "id"),

        # 8. Mileage-due fleet view
        Index("ix_vehicles_tenant_mileage_due", "tenant_id", "mileage_due"),

        # 11. Airport Transfer Support Filtering
        Index("ix_vehicles_tenant_airport_transfer", "tenant_id", "supports_airport_transfer"),

        # 12. Wedding Service Support Filtering
        Index("ix_vehicles_tenant_wedding_service", "tenant_id", "supports_wedding_service"),

        # ✅ NEW: Fast lookup for Investor's fleet
        Index("ix_vehicles_owner_id", "owner_id"),
    )
