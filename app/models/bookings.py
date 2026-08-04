import enum
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base, AuditMixin


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class Booking(Base, AuditMixin):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_number = Column(String(20), unique=True, index=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)

    # Location Details (with bounded lengths)
    destination = Column(String(255), nullable=True)
    pickup_location = Column(String(255), nullable=True)
    return_location = Column(String(255), nullable=True)
    
    # Date Range
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    original_end_date = Column(DateTime(timezone=True), nullable=True)  # For tracking extensions

    # Financial Details
    daily_rate = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), default="KES", nullable=False)

    # Status & Lifecycle
    status = Column(Enum(BookingStatus), default=BookingStatus.pending, nullable=False, index=True)
    is_archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin
    tenant = relationship("Tenant", back_populates="bookings", foreign_keys=[tenant_id])
    client = relationship("Client", back_populates="bookings", foreign_keys=[client_id])
    vehicle = relationship("Vehicle", back_populates="bookings", foreign_keys=[vehicle_id])
    
    # ✅ CRITICAL FIX: Removed 'delete-orphan' from invoices and contract.
    # Historical financial records must be preserved for audits even if a booking is archived/deleted.
    invoices = relationship("Invoice", back_populates="booking")
    contract = relationship("Contract", back_populates="booking", uselist=False)

    # ✅ ADD THESE CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # Data Integrity Check Constraints
        CheckConstraint("end_date > start_date", name="ck_bookings_valid_date_range"),
        CheckConstraint("total_amount >= 0", name="ck_bookings_total_amount_non_negative"),
        CheckConstraint("daily_rate >= 0", name="ck_bookings_daily_rate_non_negative"),
        
        # 1. Gantt Chart & Vehicle Availability (MOST IMPORTANT)
        # Query: WHERE tenant_id = ? AND start_date <= ? AND end_date >= ?
        Index("ix_bookings_tenant_dates", "tenant_id", "start_date", "end_date"),
        
        # 2. List Views with Status Filtering
        # Query: WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC
        Index("ix_bookings_tenant_status_created", "tenant_id", "status", "created_at"),
        
        # 3. Recent Bookings & Agency Health
        # Query: WHERE tenant_id = ? AND created_at >= ? ORDER BY created_at DESC
        Index("ix_bookings_tenant_created", "tenant_id", "created_at"),
        
        # 4. Soft Delete Filtering
        # Query: WHERE tenant_id = ? AND is_archived = ? ORDER BY created_at DESC
        Index("ix_bookings_tenant_archived", "tenant_id", "is_archived", "created_at"),
        
        # 5. Vehicle Utilization (Agency Health endpoint)
        # Query: WHERE tenant_id = ? AND vehicle_id = ? AND start_date <= ? AND end_date >= ?
        Index("ix_bookings_vehicle_utilization", "tenant_id", "vehicle_id", "start_date", "end_date"),
    )
