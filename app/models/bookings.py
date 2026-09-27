"""
Booking model — core rental transaction record.
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
    pending = "pending"
    confirmed = "confirmed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class CancellationReason(str, enum.Enum):
    client_cancelled = "client_cancelled"
    agency_cancelled = "agency_cancelled"
    no_show = "no_show"
    expired_unpaid = "expired_unpaid"


class Booking(Base, AuditMixin):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_number = Column(String(20), index=True, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)

    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True, index=True)
    client_provided_driver = Column(Boolean, nullable=False, default=False)
    client_driver_name = Column(String(150), nullable=True)
    client_driver_phone = Column(String(30), nullable=True)

    destination = Column(String(255), nullable=True)
    pickup_location = Column(String(255), nullable=True)
    return_location = Column(String(255), nullable=True)

    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    original_end_date = Column(DateTime(timezone=True), nullable=True)

    service_type = Column(String(30), nullable=False, default="selfdrive", server_default="selfdrive", index=True)
    service_details = Column(JSON, nullable=True)

    pickup_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_return_at = Column(DateTime(timezone=True), nullable=True)
    actual_return_at = Column(DateTime(timezone=True), nullable=True)

    pricing_day_hours = Column(Integer, nullable=True)
    pricing_grace_minutes = Column(Integer, nullable=True)
    pricing_overtime_hourly_rate = Column(Numeric(10, 2), nullable=True)

    daily_rate = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), default="KES", nullable=False)
    
    billable_days = Column(Integer, nullable=True)
    computed_total = Column(Numeric(10, 2), nullable=True)
    manually_adjusted = Column(Boolean, default=False, nullable=False)
    price_note = Column(Text, nullable=True)

    toll_fees = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    parking_fees = Column(Numeric(10, 2), nullable=False, default=0, server_default="0")

    status = Column(Enum(BookingStatus), default=BookingStatus.pending, nullable=False, index=True)

    cancellation_reason = Column(String(30), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    is_archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="bookings", foreign_keys=[tenant_id])
    client = relationship("Client", back_populates="bookings", foreign_keys=[client_id])
    vehicle = relationship("Vehicle", back_populates="bookings", foreign_keys=[vehicle_id])
    
    # ✅ FIXED: Use simple class name "InvestorContract" instead of the module path
    investor_contracts = relationship("InvestorContract", back_populates="booking")
    
    driver = relationship("Driver", back_populates="bookings", foreign_keys=[driver_id])
    invoices = relationship("Invoice", back_populates="booking")
    contract = relationship("Contract", back_populates="booking", uselist=False)
    airport_transfer = relationship("AirportTransfer", back_populates="booking", uselist=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "booking_number", name="uq_bookings_tenant_booking_number"),
        CheckConstraint("end_date > start_date", name="ck_bookings_valid_date_range"),
        CheckConstraint("total_amount >= 0", name="ck_bookings_total_amount_non_negative"),
        CheckConstraint("daily_rate >= 0", name="ck_bookings_daily_rate_non_negative"),
        CheckConstraint("toll_fees >= 0", name="ck_bookings_toll_fees_non_negative"),
        CheckConstraint("parking_fees >= 0", name="ck_bookings_parking_fees_non_negative"),
        CheckConstraint("scheduled_return_at IS NULL OR pickup_at IS NULL OR scheduled_return_at > pickup_at", name="ck_bookings_valid_schedule"),
        Index("ix_bookings_tenant_dates", "tenant_id", "start_date", "end_date"),
        Index("ix_bookings_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_bookings_tenant_created", "tenant_id", "created_at"),
        Index("ix_bookings_tenant_archived", "tenant_id", "is_archived", "created_at"),
        Index("ix_bookings_vehicle_utilization", "tenant_id", "vehicle_id", "start_date", "end_date"),
        Index("ix_bookings_driver_availability", "tenant_id", "driver_id", "start_date", "end_date"),
    )
