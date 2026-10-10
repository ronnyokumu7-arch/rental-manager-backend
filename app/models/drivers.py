# app/models/drivers.py
"""
Driver entity (tenant-scoped) — STAFF DRIVERS first (Milestone 2).

A driver record owns compliance (licence, documents), pay configuration,
and scheduling identity. Staff drivers may later link to a login via
user_id (parked).

✅ UPGRADE: client_id unparked — personal drivers link to the client who
brought them (NULL = company/staff driver). Vetting track mirrors clients.

Pay resolution order (chauffeur services):
    per-driver fee → tenant service config → derived/none
"""
import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, Index,
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


# ✅ THIS IS THE MISSING ENUM CAUSING THE IMPORT ERROR
class DriverVerificationStatus(str, enum.Enum):
    """
    ✅ VETTING TRACK — same contract as ClientVerificationStatus.
    String-backed column; enum is the code-level contract.
    """
    unverified = "unverified"
    sent = "sent"
    under_review = "under_review"
    verified = "verified"
    rejected = "rejected"


class Driver(Base, AuditMixin):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # ✅ UNPARKED: personal driver link. NULL = company/staff driver;
    # set = the client who brought this driver (chauffeur-of-client flows).
    client_id = Column(
        Integer, ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    full_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=False)
    email = Column(String(150), nullable=True)  # optional (field drivers often lack email)

    # ✅ Compliance — required for staff drivers
    id_number = Column(String(50), nullable=False)
    dl_number = Column(String(50), nullable=False)
    dl_expiry = Column(Date, nullable=True)
    # ✅ NEW: DL issue date → experience = (today - issued), derived on read
    dl_issued_date = Column(Date, nullable=True)

    # ✅ Document photos: storage keys served via the authenticated files/vault
    # pipeline (never binaries in DB).
    profile_photo_key = Column(String(255), nullable=True)
    id_front_key = Column(String(255), nullable=True)
    id_back_key = Column(String(255), nullable=True)
    dl_photo_key = Column(String(255), nullable=True)

    # ✅ VETTING TRACK (mirrors clients; String-backed + check constraint)
    verification_status = Column(
        String(20),
        nullable=False,
        default=DriverVerificationStatus.unverified.value,
        server_default=DriverVerificationStatus.unverified.value,
    )
    verification_token = Column(String(64), nullable=True, unique=True)
    verification_expires_at = Column(DateTime(timezone=True), nullable=True)
    # ✅ Camera-only capture binding driver ↔ physical ID (follows _key naming)
    selfie_with_id_key = Column(String(255), nullable=True)
    vetted_at = Column(DateTime(timezone=True), nullable=True)
    vetted_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    rejection_notes = Column(Text, nullable=True)

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
        # ✅ NEW: vetting track guard
        CheckConstraint(
            "verification_status IN ('unverified', 'sent', 'under_review', 'verified', 'rejected')",
            name="ck_driver_verification_status_valid",
        ),
        # ✅ NEW: double-entry defense (per tenant) — audit confirmed 0 dupes
        UniqueConstraint("tenant_id", "phone", name="uq_driver_tenant_phone"),
        UniqueConstraint("tenant_id", "id_number", name="uq_driver_tenant_id_number"),
        UniqueConstraint("tenant_id", "dl_number", name="uq_driver_tenant_dl_number"),
        # ✅ NEW: vetting review queue
        Index("ix_drivers_tenant_verification", "tenant_id", "verification_status"),
    )
