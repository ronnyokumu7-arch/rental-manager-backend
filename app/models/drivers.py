# app/models/drivers.py
"""
Driver entity (tenant-scoped).

Supports in-house AND contracted drivers, with per-driver rate overrides
that layer over the tenant's service pricing config:

    per-driver rate → tenant service config → derived/none

Compliance fields (dl_number, dl_expiry) enable future licence-expiry alerts.
delivery_commission feeds vehicle delivery/collection task payouts
(duty scheduler, Milestone 2.2).
"""
import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, String,
)

from app.db.database import Base, AuditMixin


class DriverEmploymentType(str, enum.Enum):
    in_house = "in_house"
    contracted = "contracted"


class DriverStatus(str, enum.Enum):
    available = "available"
    on_trip = "on_trip"
    on_leave = "on_leave"
    suspended = "suspended"


class Driver(Base, AuditMixin):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    full_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(150), nullable=True)

    # ✅ Compliance (future: licence-expiry alerts)
    id_number = Column(String(50), nullable=True)
    dl_number = Column(String(50), nullable=True)
    dl_expiry = Column(Date, nullable=True)

    # ✅ String (not DB ENUM) → new values ship without ALTER TYPE migrations
    employment_type = Column(
        String(20), nullable=False, default=DriverEmploymentType.in_house,
    )
    status = Column(
        String(20), nullable=False, default=DriverStatus.available, index=True,
    )

    # ✅ Per-driver rate overrides (NULL → fall back to tenant service config)
    daily_fee = Column(Numeric(10, 2), nullable=True)
    overtime_hourly_fee = Column(Numeric(10, 2), nullable=True)
    night_accommodation_fee = Column(Numeric(10, 2), nullable=True)

    # ✅ Per vehicle delivery/collection task (duty scheduler payouts)
    delivery_commission = Column(Numeric(10, 2), nullable=True)

    # ✅ PARKED: link when driver logins / duty scheduler ship
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    is_archived = Column(Boolean, nullable=False, default=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "daily_fee IS NULL OR daily_fee >= 0",
            name="ck_driver_daily_fee_non_negative",
        ),
        CheckConstraint(
            "overtime_hourly_fee IS NULL OR overtime_hourly_fee >= 0",
            name="ck_driver_ot_fee_non_negative",
        ),
        CheckConstraint(
            "night_accommodation_fee IS NULL OR night_accommodation_fee >= 0",
            name="ck_driver_accommodation_non_negative",
        ),
        CheckConstraint(
            "delivery_commission IS NULL OR delivery_commission >= 0",
            name="ck_driver_delivery_commission_non_negative",
        ),
    )
