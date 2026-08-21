# app/models/pricing.py
"""
Service Pricing Configuration (tenant-scoped).

Backend-level service definitions:
  - selfdrive:  1 day = 24h rolling from pickup, 1h grace, hourly overtime (capped).
  - with_driver: SAME 24h rolling clock as selfdrive (standard selfdrive rates)
                 + driver fee stack: daily fee + driver overtime + accommodation.
  - wedding:    1 day = max 12h per calendar day; extra hours billable/forgivable.
  - PARKED (defined, inactive): airport_transfer, safari, inter_county, city_excursion.
"""
import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Integer,
    Numeric, String, UniqueConstraint,
)

from app.db.database import Base, AuditMixin


class ServiceType(str, enum.Enum):
    selfdrive = "selfdrive"
    with_driver = "with_driver"
    wedding = "wedding"
    # ✅ PARKED: backend-defined, activated when their pricing models ship:
    # airport_transfer = "airport_transfer"
    # safari = "safari"
    # inter_county = "inter_county"
    # city_excursion = "city_excursion"


class ServicePricingConfig(Base, AuditMixin):
    __tablename__ = "service_pricing_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # ✅ String (not DB ENUM) → new services ship without ALTER TYPE migrations
    service_type = Column(String(30), nullable=False)

    # Hours that constitute one billable day (24 selfdrive/with_driver, 12 wedding)
    day_hours = Column(Integer, nullable=False, default=24)

    # Free buffer after the rental period exhausts, in minutes (standard: 60)
    grace_minutes = Column(Integer, nullable=False, default=60)

    # Hourly overtime rate for the VEHICLE. NULL → derived: daily_rate / day_hours
    overtime_hourly_rate = Column(Numeric(10, 2), nullable=True)

    # ✅ Safety valve: vehicle overtime can never exceed one full day rate
    overtime_cap_at_day_rate = Column(Boolean, nullable=False, default=True)

    # ✅ MILESTONE 1: DRIVER FEE STACK (with_driver / wedding when configured)
    # Driver's base fee per rental day (24h block / 12h wedding day)
    driver_daily_fee = Column(Numeric(10, 2), nullable=True)
    # Driver's overtime per hour beyond grace (NULL → no driver OT charged)
    driver_overtime_hourly_fee = Column(Numeric(10, 2), nullable=True)
    # Driver accommodation per overnight stay (NULL → not charged).
    # Nights = included_days - 1 (only multi-day rentals).
    driver_night_accommodation_fee = Column(Numeric(10, 2), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # One config row per tenant per service type (tenant isolation enforced)
        UniqueConstraint("tenant_id", "service_type", name="uq_pricing_tenant_service_type"),
        CheckConstraint("day_hours > 0", name="ck_pricing_day_hours_positive"),
        CheckConstraint("grace_minutes >= 0", name="ck_pricing_grace_non_negative"),
        CheckConstraint(
            "overtime_hourly_rate IS NULL OR overtime_hourly_rate >= 0",
            name="ck_pricing_overtime_rate_non_negative",
        ),
        CheckConstraint(
            "driver_daily_fee IS NULL OR driver_daily_fee >= 0",
            name="ck_pricing_driver_daily_fee_non_negative",
        ),
        CheckConstraint(
            "driver_overtime_hourly_fee IS NULL OR driver_overtime_hourly_fee >= 0",
            name="ck_pricing_driver_ot_fee_non_negative",
        ),
        CheckConstraint(
            "driver_night_accommodation_fee IS NULL OR driver_night_accommodation_fee >= 0",
            name="ck_pricing_driver_accommodation_non_negative",
        ),
    )
