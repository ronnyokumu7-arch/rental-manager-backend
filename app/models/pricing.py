"""
Service Pricing Configuration (tenant-scoped).

Pricing architecture (Milestone 1.1):
  * Service DEFINITIONS live in app/services/catalog.py (billing model defaults,
    categories, driver requirements, live/parked flags).
  * This table stores tenant RATE DATA per service_type.
  * billing_model (nullable) overrides the catalog default per tenant —
    e.g. one agency runs airport_transfer as fixed_route, another as distance_time.
  * rate_extras (JSONB) is the flexible rate card: per_km, base_fare, fixed_rate,
    half/full-day rates, min_charge_hours, route_rates map, per_stop_rate.
    New pricing models ship WITHOUT schema migrations.

Billing models (strategies in app/services/pricing.py):
  rolling_24h    ANY part of a 24h block bills as 1 FULL day (min 1 day).
                 30 min, 10 h, 24 h → 1 day. 24h01m → 2 days. 47h → 2 days.
                 ✅ NO hourly proration, NO grace in pricing.
                 grace_minutes is OPERATIONAL ONLY (overdue alerts on the
                 frontend/dashboard), never part of the rental price.
  event_base     flat base hours (12h wedding) + hourly add-ons.
  hourly         rate × hours with min charge.
  package        half-day / full-day blocks + extra hours.
  fixed_route    flat rate per standard route (route_rates map).
  distance_time  base fare + per-km + per-minute.
  route_stops    per place visited (future).
"""
import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Integer,
    Numeric, String, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.database import Base, AuditMixin


class ServiceType(str, enum.Enum):
    # ✅ Current keys (mirror app/services/catalog.py)
    selfdrive = "selfdrive"
    chauffeur_pro_driver = "chauffeur_pro_driver"
    chauffeur_wedding = "chauffeur_wedding"
    # Deprecated aliases — kept so historical references never break:
    with_driver = "with_driver"    # → chauffeur_pro_driver
    wedding = "wedding"            # → chauffeur_wedding
    # ✅ PARKED: chauffeur_hourly, corporate, city_excursion,
    # airport_transfer, chauffeur_taxi, route_stops_service (see catalog.py)


class ServicePricingConfig(Base, AuditMixin):
    __tablename__ = "service_pricing_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # ✅ String (not DB ENUM) → new services ship without ALTER TYPE migrations
    service_type = Column(String(30), nullable=False)

    # ✅ MILESTONE 1.1: strategy selector. NULL → catalog default for this service.
    # Lets one agency run airport_transfer as fixed_route, another as distance_time.
    billing_model = Column(String(30), nullable=True)

    # ✅ MILESTONE 1.1: flexible rate card (JSONB).
    # Known keys: per_hour, per_km, per_min, base_fare, fixed_rate,
    # half_day_rate, half_day_hours, full_day_rate, full_day_hours,
    # min_charge_hours, route_rates {"JKIA_CBD": 2500, ...}, per_stop_rate.
    # Strategies read only what they need → new models, zero migrations.
    rate_extras = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Hours that constitute one billable day (24 selfdrive/pro_driver, 12 wedding).
    # rolling_24h: billable_days = max(1, ceil(duration / day_hours)).
    day_hours = Column(Integer, nullable=False, default=24)

    # ✅ OPERATIONAL ONLY: buffer after rental end used for OVERDUE ALERTS
    # (frontend/dashboard flags a trip overdue grace_minutes after return time).
    # NEVER used in rental price calculation.
    grace_minutes = Column(Integer, nullable=False, default=60)

    # Hourly rate used ONLY by non-rolling models (event_base/hourly/package
    # add-ons). NOT used by rolling_24h — partial blocks bill as full days.
    # NULL → derived: daily_rate / day_hours
    overtime_hourly_rate = Column(Numeric(10, 2), nullable=True)

    # ✅ Safety valve for the models that DO charge hourly: overtime can never
    # exceed one full day rate. Irrelevant for rolling_24h.
    overtime_cap_at_day_rate = Column(Boolean, nullable=False, default=True)

    # ✅ MILESTONE 1: DRIVER FEE STACK (chauffeur services when configured)
    # Driver's base fee per rental day (24h block / 12h event day)
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
