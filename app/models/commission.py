# app/models/commission.py
import enum

from sqlalchemy import (
    Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base, AuditMixin


class CommissionStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"
    waived = "waived"   # ✅ Super admin goodwill waiver ("don't scare them away")


class CommissionEvent(Base, AuditMixin):
    """
    Platform commission ledger (Pay-As-You-Go).

    One row per STARTED trip (booking activation). The amount is snapshotted
    at event time so future rate changes never rewrite history.
    `booking_id` is unique → a trip can NEVER be double-charged.
    """
    __tablename__ = "commission_events"

    id = Column(Integer, primary_key=True, index=True)

    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    booking_id = Column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False, unique=True,  # ✅ One commission per trip, forever
    )

    # ✅ Snapshotted at trip start (default 150, super-admin configurable later)
    amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")

    status = Column(
        Enum(CommissionStatus), nullable=False, default=CommissionStatus.unpaid
    )

    # The commission trigger moment (keys handed over)
    trip_started_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Settlement metadata
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(String(100), nullable=True)

    tenant = relationship("Tenant", backref="commission_events")
    booking = relationship("Booking", backref="commission_event")

    __table_args__ = (
        # "What does this tenant owe right now?" (dashboard + soft-lock checks)
        Index("ix_commission_tenant_status", "tenant_id", "status"),
        # "Trips started today / yesterday" (daily reset + 00:00H settlement job)
        Index("ix_commission_tenant_started", "tenant_id", "trip_started_at"),
    )
