# app/services/pricing.py
"""
Time-Aware Pricing Engine + Backend Service Registry (Milestone 1).

LIVE SERVICES:
  selfdrive    → 24h rolling clock from pickup_at; 1h grace; hourly OT (capped at day rate).
  with_driver  → SAME 24h rolling clock (standard selfdrive rates)
                 + driver fee stack: daily fee + driver OT + accommodation per night.
  wedding      → 12h max per calendar day; extra hours billable or waivable.

PARKED (backend-defined, engine rejects until activated):
  airport_transfer, safari, inter_county, city_excursion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import ServicePricingConfig

SELFDRIVE = "selfdrive"
WITH_DRIVER = "with_driver"
WEDDING = "wedding"

CENT = Decimal("0.01")

# Grace defaults per billing model (minutes)
DEFAULT_GRACE_MINUTES = {"rolling": 60, "calendar_day": 30}


# ---------------------------------------------------------------------------
# BACKEND SERVICE REGISTRY (single source of truth for service semantics)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServiceDefinition:
    key: str
    label: str
    day_hours: int
    billing_model: str        # "rolling" | "calendar_day" | "parked"
    includes_driver: bool
    is_live: bool


SERVICE_REGISTRY: Dict[str, ServiceDefinition] = {
    SELFDRIVE: ServiceDefinition(SELFDRIVE, "Self Drive", 24, "rolling", False, True),
    WITH_DRIVER: ServiceDefinition(WITH_DRIVER, "With Driver", 24, "rolling", True, True),
    WEDDING: ServiceDefinition(WEDDING, "Wedding Car Hire", 12, "calendar_day", True, True),
    # ✅ PARKED: defined now, activated later with their own pricing models
    "airport_transfer": ServiceDefinition("airport_transfer", "Airport Transfer", 0, "parked", True, False),
    "safari": ServiceDefinition("safari", "Safari", 0, "parked", True, False),
    "inter_county": ServiceDefinition("inter_county", "Inter-County", 0, "parked", True, False),
    "city_excursion": ServiceDefinition("city_excursion", "City Excursion", 0, "parked", True, False),
}


def get_service_definition(service_type: str) -> ServiceDefinition:
    return SERVICE_REGISTRY.get(service_type, SERVICE_REGISTRY[SELFDRIVE])


def live_services() -> List[ServiceDefinition]:
    return [s for s in SERVICE_REGISTRY.values() if s.is_live]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PricingLine:
    description: str
    quantity: str
    amount: Decimal


@dataclass
class PricingResult:
    service_type: str
    service_label: str
    pickup_at: datetime
    return_at: datetime
    daily_rate: Decimal
    day_hours: int
    grace_minutes: int
    overtime_hourly_rate: Decimal
    included_days: int
    extra_hours: int
    grace_used_minutes: int
    base_charge: Decimal
    overtime_charge: Decimal
    overtime_waivable: bool
    driver_daily_fee: Decimal
    driver_overtime_fee: Decimal
    driver_accommodation_fee: Decimal
    driver_charge: Decimal
    total: Decimal
    lines: List[PricingLine] = field(default_factory=list)


def calculate(
    *,
    service_type: str,
    pickup_at: datetime,
    return_at: datetime,
    daily_rate: Decimal,
    day_hours: Optional[int] = None,
    grace_minutes: Optional[int] = None,
    overtime_hourly_rate: Optional[Decimal] = None,
    cap_overtime_at_day_rate: bool = True,
    driver_daily_fee: Optional[Decimal] = None,
    driver_overtime_hourly_fee: Optional[Decimal] = None,
    driver_night_accommodation_fee: Optional[Decimal] = None,
) -> PricingResult:
    """Pure pricing calculation. Raises ValueError on invalid/parked service."""
    if return_at <= pickup_at:
        raise ValueError("return_at must be strictly after pickup_at")

    definition = get_service_definition(service_type)
    if not definition.is_live:
        raise ValueError(f"Service '{service_type}' is not yet available.")

    day_hours = day_hours or definition.day_hours
    grace_minutes = (
        grace_minutes
        if grace_minutes is not None
        else DEFAULT_GRACE_MINUTES.get(definition.billing_model, 60)
    )

    daily_rate = Decimal(daily_rate)
    hourly_rate = (
        Decimal(overtime_hourly_rate)
        if overtime_hourly_rate is not None
        else daily_rate / Decimal(day_hours)
    )

    elapsed_seconds = (return_at - pickup_at).total_seconds()
    day_seconds = day_hours * 3600
    grace_seconds = grace_minutes * 60

    if definition.billing_model == "calendar_day":
        # WEDDING: 1 day per calendar day touched; each includes day_hours (12).
        included_days = (return_at.date() - pickup_at.date()).days + 1
        included_seconds = included_days * day_seconds
        extra_seconds = max(0.0, elapsed_seconds - included_seconds)
        grace_used_seconds = min(extra_seconds, grace_seconds)
        overtime_seconds = max(0.0, extra_seconds - grace_seconds)
    else:
        # ROLLING (selfdrive / with_driver): 24h countdown from pickup_at.
        full_days = int(elapsed_seconds // day_seconds)
        remainder_seconds = elapsed_seconds - (full_days * day_seconds)
        included_days = max(1, full_days)
        grace_used_seconds = 0.0
        overtime_seconds = 0.0
        if full_days >= 1 and remainder_seconds > 0:
            grace_used_seconds = min(remainder_seconds, grace_seconds)
            overtime_seconds = max(0.0, remainder_seconds - grace_seconds)

    extra_hours = math.ceil(overtime_seconds / 3600) if overtime_seconds > 0 else 0
    grace_used_minutes = int(grace_used_seconds // 60)

    # --- Vehicle charges ---
    base_charge = _q(daily_rate * included_days)
    raw_overtime = hourly_rate * extra_hours
    if cap_overtime_at_day_rate and extra_hours > 0:
        raw_overtime = min(raw_overtime, daily_rate)
    overtime_charge = _q(raw_overtime)

    # --- Driver fee stack (only when configured) ---
    ZERO = Decimal("0.00")
    driver_daily = _q(Decimal(driver_daily_fee) * included_days) if driver_daily_fee is not None else ZERO
    driver_ot = (
        _q(Decimal(driver_overtime_hourly_fee) * extra_hours)
        if driver_overtime_hourly_fee is not None and extra_hours > 0
        else ZERO
    )
    nights = max(0, included_days - 1)
    driver_accom = (
        _q(Decimal(driver_night_accommodation_fee) * nights)
        if driver_night_accommodation_fee is not None and nights > 0
        else ZERO
    )
    driver_charge = driver_daily + driver_ot + driver_accom

    total = _q(base_charge + overtime_charge + driver_charge)

    lines = [
        PricingLine(
            description=f"{definition.label} rental",
            quantity=f"{included_days} day(s) x {day_hours}h",
            amount=base_charge,
        )
    ]
    if extra_hours > 0:
        lines.append(PricingLine("Vehicle overtime (after grace)", f"{extra_hours} hr(s)", overtime_charge))
    if driver_daily > 0:
        lines.append(PricingLine("Driver fee", f"{included_days} day(s)", driver_daily))
    if driver_ot > 0:
        lines.append(PricingLine("Driver overtime", f"{extra_hours} hr(s)", driver_ot))
    if driver_accom > 0:
        lines.append(PricingLine("Driver accommodation", f"{nights} night(s)", driver_accom))

    return PricingResult(
        service_type=service_type,
        service_label=definition.label,
        pickup_at=pickup_at,
        return_at=return_at,
        daily_rate=_q(daily_rate),
        day_hours=day_hours,
        grace_minutes=grace_minutes,
        overtime_hourly_rate=_q(hourly_rate),
        included_days=included_days,
        extra_hours=extra_hours,
        grace_used_minutes=grace_used_minutes,
        base_charge=base_charge,
        overtime_charge=overtime_charge,
        overtime_waivable=(definition.billing_model == "calendar_day"),
        driver_daily_fee=driver_daily,
        driver_overtime_fee=driver_ot,
        driver_accommodation_fee=driver_accom,
        driver_charge=driver_charge,
        total=total,
        lines=lines,
    )


async def get_pricing_config(
    db: AsyncSession, tenant_id: int, service_type: str
) -> Optional[ServicePricingConfig]:
    stmt = select(ServicePricingConfig).where(
        ServicePricingConfig.tenant_id == tenant_id,
        ServicePricingConfig.service_type == service_type,
        ServicePricingConfig.is_active.is_(True),
    )
    return (await db.execute(stmt)).scalars().first()


def snapshot_fields(config: Optional[ServicePricingConfig], service_type: str) -> dict:
    definition = get_service_definition(service_type)
    return {
        "pricing_day_hours": (
            config.day_hours if config else definition.day_hours
        ),
        "pricing_grace_minutes": (
            config.grace_minutes if config
            else DEFAULT_GRACE_MINUTES.get(definition.billing_model, 60)
        ),
        "pricing_overtime_hourly_rate": config.overtime_hourly_rate if config else None,
    }


async def price_booking(db: AsyncSession, booking, daily_rate: Decimal) -> PricingResult:
    """
    Price a booking using (priority order):
      1. Snapshotted pricing fields on the booking
      2. Active tenant ServicePricingConfig
      3. Registry defaults
    Falls back to start_date/end_date when pickup_at/scheduled_return_at are NULL.
    """
    service_type = getattr(booking, "service_type", None) or SELFDRIVE
    pickup_at = booking.pickup_at or booking.start_date
    return_at = booking.scheduled_return_at or booking.end_date

    config = await get_pricing_config(db, booking.tenant_id, service_type)
    snap = snapshot_fields(config, service_type)

    return calculate(
        service_type=service_type,
        pickup_at=pickup_at,
        return_at=return_at,
        daily_rate=daily_rate,
        day_hours=booking.pricing_day_hours or snap["pricing_day_hours"],
        grace_minutes=booking.pricing_grace_minutes or snap["pricing_grace_minutes"],
        overtime_hourly_rate=booking.pricing_overtime_hourly_rate
        or snap["pricing_overtime_hourly_rate"],
        cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
        driver_daily_fee=config.driver_daily_fee if config else None,
        driver_overtime_hourly_fee=config.driver_overtime_hourly_fee if config else None,
        driver_night_accommodation_fee=config.driver_night_accommodation_fee if config else None,
    )
