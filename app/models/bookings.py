"""
Booking model — core rental transaction record.

✅ PHASE 1: Self-drive pricing snapshot fields added:
  - billable_days: locked day count at creation
  - computed_total: engine result (what the formula said)
  - manually_adjusted: boolean flag (human touched the price)
  - price_note: optional free-text reason for adjustment
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Index, UniqueConstraint, Text, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base, AuditMixin


class BookingStatus(str, enum.Enum):
    """
    ✅ 5-state lifecycle (no_show removed — it was a redundant terminal state).

    pending    → created, awaiting client quotation acceptance
    confirmed  → client accepted the quotation (strong business signal)
    active     → trip started (handover done)
    completed  → returned, closed
    cancelled  → voided (reason captured in cancellation_reason)
    """
    pending = "pending"
    confirmed = "confirmed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class CancellationReason(str, enum.Enum):
    """
    ✅ WHY a booking was cancelled — preserved as data (not a status) so the
    refund-policy engine and analytics can distinguish outcomes.

    ✅ STORED AS String(30) in the DB (not a native enum) — consistent with
    service_type, so future reasons ship without ALTER TYPE migrations.
    This class is the application-level validator: the lifecycle service
    coerces via CancellationReason(value) (raises ValueError if invalid)
    before writing to the column.
    """
    client_cancelled = "client_cancelled"   # client backed out in advance
    agency_cancelled = "agency_cancelled"   # operator voided it
    no_show = "no_show"                     # client never arrived (forfeit tier)
    expired_unpaid = "expired_unpaid"       # quotation/invoice lapsed unpaid


class Booking(Base, AuditMixin):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)

    # ✅ FIXED: uniqueness is PER TENANT (composite constraint below), not global
    booking_number = Column(String(20), index=True, nullable=False)

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)

    # ✅ MILESTONE 2: Driver assignment (nullable — assigned at confirmation or pickup)
    driver_id = Column(
        Integer, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    client_provided_driver = Column(Boolean, nullable=False, default=False)
    client_driver_name = Column(String(150), nullable=True)
    client_driver_phone = Column(String(30), nullable=True)

    # Location Details (with bounded lengths)
    destination = Column(String(255), nullable=True)
    pickup_location = Column(String(255), nullable=True)
    return_location = Column(String(255), nullable=True)

    # Date Range
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    original_end_date = Column(DateTime(timezone=True), nullable=True)  # For tracking extensions

    # ✅ MILESTONE 1: Service type + time-aware scheduling
    # String (not DB ENUM) → future services ship without ALTER TYPE migrations.
    service_type = Column(
        String(30), nullable=False,
        default="selfdrive", server_default="selfdrive", index=True,
    )

    # ✅ MILESTONE 3: Service-specific details (JSON)
    # Stores add-ons and configurations specific to the service_type 
    # (e.g., wedding extra hours, decoration fees, airport tolls).
    # Keeps the core Booking table lean and avoids nullable column bloat.
    service_details = Column(JSON, nullable=True)

    # Exact countdown origin: 1 rental day = 24 hours (self-drive).
    # Nullable for backward compat — falls back to start_date/end_date.
    pickup_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_return_at = Column(DateTime(timezone=True), nullable=True)
    # Set when the vehicle is physically returned (late-return reconciliation).
    actual_return_at = Column(DateTime(timezone=True), nullable=True)

    # ✅ LEGACY PRICING SNAPSHOT (kept nullable for old data, no longer used in Phase 1)
    pricing_day_hours = Column(Integer, nullable=True)          # 24 / 12
    pricing_grace_minutes = Column(Integer, nullable=True)      # 60 / 30
    pricing_overtime_hourly_rate = Column(Numeric(10, 2), nullable=True)

    # Financial Details
    daily_rate = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), default="KES", nullable=False)
    
    # ✅ PHASE 1: Self-Drive Pricing Snapshot (immutable after creation)
    billable_days = Column(Integer, nullable=True)          # Locked day count
    computed_total = Column(Numeric(10, 2), nullable=True)  # Engine result
    manually_adjusted = Column(Boolean, default=False, nullable=False)  # Human override flag
    price_note = Column(Text, nullable=True)                # Optional reason for adjustment

    # Status & Lifecycle
    status = Column(Enum(BookingStatus), default=BookingStatus.pending, nullable=False, index=True)

    # ✅ CANCELLATION METADATA (replaces the removed no_show status).
    # Terminal status is always `cancelled`; the reason preserves the business
    # meaning for refund-policy tiers (lead_time × reason) and no-show analytics.
    # Stored as String(30); validated app-side via CancellationReason(value).
    cancellation_reason = Column(String(30), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    is_archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin
    tenant = relationship("Tenant", back_populates="bookings", foreign_keys=[tenant_id])
    client = relationship("Client", back_populates="bookings", foreign_keys=[client_id])
    vehicle = relationship("Vehicle", back_populates="bookings", foreign_keys=[vehicle_id])
    driver = relationship("Driver", back_populates="bookings", foreign_keys=[driver_id])

    # ✅ CRITICAL FIX: Removed 'delete-orphan' from invoices and contract.
    # Historical financial records must be preserved for audits even if a booking is archived/deleted.
    invoices = relationship("Invoice", back_populates="booking")
    contract = relationship("Contract", back_populates="booking", uselist=False)

    # ✅ MILESTONE 2: 1:1 Airport Transfer extension
    airport_transfer = relationship("AirportTransfer", back_populates="booking", uselist=False)

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # ✅ NEW: document numbers must be unique PER TENANT (not globally)
        UniqueConstraint("tenant_id", "booking_number", name="uq_bookings_tenant_booking_number"),

        # Data Integrity Check Constraints
        CheckConstraint("end_date > start_date", name="ck_bookings_valid_date_range"),
        CheckConstraint("total_amount >= 0", name="ck_bookings_total_amount_non_negative"),
        CheckConstraint("daily_rate >= 0", name="ck_bookings_daily_rate_non_negative"),
        CheckConstraint(
            "scheduled_return_at IS NULL OR pickup_at IS NULL OR scheduled_return_at > pickup_at",
            name="ck_bookings_valid_schedule",
        ),

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

        # 6. Driver Availability (Duty Scheduler)
        # Query: WHERE tenant_id = ? AND driver_id = ? AND start_date <= ? AND end_date >= ?
        Index("ix_bookings_driver_availability", "tenant_id", "driver_id", "start_date", "end_date"),
    )
