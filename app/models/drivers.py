# app/models/drivers.py
"""
Driver entity (tenant-scoped) — STAFF DRIVERS first (Milestone 2).

A driver record owns compliance (licence, documents), pay configuration,
and scheduling identity. Staff drivers may later link to a login via
user_id (parked). Contract & client drivers are parked expansions.

Pay resolution order (chauffeur services):
    per-driver fee → tenant service config → derived/none
"""
import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, String,
)
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class DriverEmploymentType(str, enum.Enum):
    in_house = "in_house"        # ✅ LIVE: staff driver
    contracted = "contracted"    # 🅿️ PARKED


class DriverStatus(str, enum.Enum):
    available = "available"
    on_trip = "on_trip"
    on_leave = "on_leave"
    suspended = "suspended"


class DriverPayMode(str, enum.Enum):
    commission = "commission"         # paid per task / commission
    fixed_per_job = "fixed_per_job"   # fixed price per job (configurable per task later)
    payroll = "payroll"               # 🅿️ PARKED (future payroll engine)


class Driver(Base, AuditMixin):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    full_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(150), nullable=True)  # optional (field drivers often lack email)

    # ✅ Compliance — required for staff drivers
    id_number = Column(String(50), nullable=False)
    dl_number = Column(String(50), nullable=False)
    dl_expiry = Column(Date, nullable=True)

    # ✅ Document photos: storage keys served via the authenticated files/vault
    # pipeline (never binaries in DB).
    profile_photo_key = Column(String(255), nullable=True)
    id_front_key = Column(String(255), nullable=True)
    id_back_key = Column(String(255), nullable=True)
    dl_photo_key = Column(String(255), nullable=True)

    # ✅ String (not DB ENUM) → new values ship without ALTER TYPE migrations
    employment_type = Column(
        String(20), nullable=False, default=DriverEmploymentType.in_house,
    )
    status = Column(
        String(20), nullable=False, default=DriverStatus.available, index=True,
    )
    pay_mode = Column(
        String(20), nullable=False, default=DriverPayMode.commission,
    )

    # ✅ Per-driver rate overrides (NULL → fall back to tenant service config)
    daily_fee = Column(Numeric(10, 2), nullable=True)
    overtime_hourly_fee = Column(Numeric(10, 2), nullable=True)
    night_accommodation_fee = Column(Numeric(10, 2), nullable=True)

    # ✅ Per vehicle delivery/collection task (duty scheduler payouts)
    delivery_commission = Column(Numeric(10, 2), nullable=True)

    # 🅿️ PARKED: link when staff-driver logins / duty scheduler app ship
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    is_archived = Column(Boolean, nullable=False, default=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # ✅ MILESTONE 2: Back-reference to bookings (required for back_populates)
    bookings = relationship("Booking", back_populates="driver")

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
        CheckConstraint(
            "pay_mode IN ('commission', 'fixed_per_job', 'payroll')",
            name="ck_driver_pay_mode_valid",
        ),
        CheckConstraint(
            "employment_type IN ('in_house', 'contracted')",
            name="ck_driver_employment_type_valid",
        ),
        CheckConstraint(
            "status IN ('available', 'on_trip', 'on_leave', 'suspended')",
            name="ck_driver_status_valid",
        ),
    )
