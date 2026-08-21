# app/services/pricing.py
"""
Time-Aware Pricing Engine — strategy dispatch over a shared rate card.

Billing models (selected via tenant config override or catalog default):
  rolling_24h    24h countdown from pickup; grace; hourly OT (capped at day rate);
                 driver fee stack (daily + OT + accommodation).
  event_base     single event: flat base (base_hours, e.g. 12h wedding) +
                 hourly add-ons (waivable); driver stack applies.
  hourly         rate × hours with min_charge_hours; all-inclusive (no driver stack).
  package        half_day (≤ half_day_hours) OR full_day (≤ full_day_hours)
                 + hourly add-ons beyond full_day.
  fixed_route    flat rate from rate_extras.route_rates[route_key] or fixed_rate.
  distance_time  base_fare + km × per_km + minutes × per_min.
  route_stops    stops × per_stop_rate (parked).

Rate card = rate_extras JSONB keys:
  per_hour, per_km, per_min, base_fare, fixed_rate, half_day_rate, half_day_hours,
  full_day_rate, full_day_hours, min_charge_hours, route_rates, per_stop_rate.

DB access limited to get_pricing_config(); calculate() is pure.
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
from app.services.catalog import (
    BillingModel, get_service, live_services, resolve_key,
)

SELFDRIVE = "selfdrive"

CENT = Decimal("0.01")

DEFAULT_GRACE_MINUTES: Dict[str, int] = {
    BillingModel.rolling_24h.value: 60,
    BillingModel.event_base.value: 30,
    BillingModel.hourly.value: 0,
    BillingModel.package.value: 0,
    BillingModel.fixed_route.value: 0,
    BillingModel.distance_time.value: 0,
    BillingModel.route_stops.value: 0,
}


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value) -> Decimal:
    """JSONB-safe Decimal conversion (float/int/str/Decimal)."""
    return Decimal(str(value))


@dataclass
class PricingLine:
    description: str
    quantity: str
    amount: Decimal


@dataclass
class PricingResult:
    service_type: str
    service_label: str
    billing_model: str
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
    billing_model: Optional[str] = None,
    day_hours: Optional[int] = None,
    grace_minutes: Optional[int] = None,
    overtime_hourly_rate: Optional[Decimal] = None,
    cap_overtime_at_day_rate: bool = True,
    driver_daily_fee: Optional[Decimal] = None,
    driver_overtime_hourly_fee: Optional[Decimal] = None,
    driver_night_accommodation_fee: Optional[Decimal] = None,
    rate_extras: Optional[dict] = None,
    distance_km: Optional[Decimal] = None,
    route_key: Optional[str] = None,
    stops: Optional[int] = None,
) -> PricingResult:
    """Pure pricing calculation. Raises ValueError on invalid input/parked service."""
    if return_at <= pickup_at:
        raise ValueError("return_at must be strictly after pickup_at")

    definition = get_service(service_type)
    if not definition.is_live:
        raise ValueError(f"Service '{service_type}' is not yet available.")

    model = billing_model or definition.billing_model.value
    day_hours = day_hours or definition.base_hours or 24
    grace_minutes = (
        grace_minutes if grace_minutes is not None
        else DEFAULT_GRACE_MINUTES.get(model, 0)
    )
    extras = rate_extras or {}
    daily_rate = Decimal(daily_rate)

    derived_hourly = (
        Decimal(overtime_hourly_rate) if overtime_hourly_rate is not None
        else daily_rate / Decimal(day_hours)
    )
    per_hour = (
        _dec(extras["per_hour"]) if "per_hour" in extras
        else derived_hourly
    )

    elapsed_seconds = (return_at - pickup_at).total_seconds()
    day_seconds = day_hours * 3600
    grace_seconds = grace_minutes * 60

    ZERO = Decimal("0.00")
    included_days = 0
    extra_hours = 0
    grace_used_seconds = 0.0
    base_charge = ZERO
    overtime_charge = ZERO
    overtime_waivable = False
    lines: List[PricingLine] = []

    # ── rolling_24h ─────────────────────────────────────────────
    if model == BillingModel.rolling_24h.value:
        full_days = int(elapsed_seconds // day_seconds)
        remainder = elapsed_seconds - (full_days * day_seconds)
        included_days = max(1, full_days)
        if full_days >= 1 and remainder > 0:
            grace_used_seconds = min(remainder, grace_seconds)
            overtime_seconds = max(0.0, remainder - grace_seconds)
            extra_hours = math.ceil(overtime_seconds / 3600) if overtime_seconds else 0
        base_charge = _q(daily_rate * included_days)
        lines.append(PricingLine(
            f"{definition.display_name} rental",
            f"{included_days} day(s) x {day_hours}h", base_charge))
        if extra_hours:
            raw = per_hour * extra_hours
            if cap_overtime_at_day_rate:
                raw = min(raw, daily_rate)
            overtime_charge = _q(raw)
            lines.append(PricingLine("Vehicle overtime (after grace)",
                                     f"{extra_hours} hr(s)", overtime_charge))

    # ── event_base (wedding) ────────────────────────────────────
    elif model == BillingModel.event_base.value:
        included_days = 1
        base_seconds = day_hours * 3600
        extra_seconds = max(0.0, elapsed_seconds - base_seconds)
        grace_used_seconds = min(extra_seconds, grace_seconds)
        overtime_seconds = max(0.0, extra_seconds - grace_seconds)
        extra_hours = math.ceil(overtime_seconds / 3600) if overtime_seconds else 0
        base_charge = _q(daily_rate)   # flat event package (12h base)
        lines.append(PricingLine(
            f"{definition.display_name} package",
            f"1 event x {day_hours}h base", base_charge))
        if extra_hours:
            overtime_charge = _q(per_hour * extra_hours)
            overtime_waivable = True
            lines.append(PricingLine("Event add-on hours (waivable)",
                                     f"{extra_hours} hr(s)", overtime_charge))

    # ── hourly ──────────────────────────────────────────────────
    elif model == BillingModel.hourly.value:
        min_hours = int(extras.get("min_charge_hours", 2))
        hours = max(min_hours, math.ceil(elapsed_seconds / 3600))
        base_charge = _q(per_hour * hours)
        lines.append(PricingLine(
            f"{definition.display_name} (hourly, min {min_hours}h)",
            f"{hours} hr(s)", base_charge))

    # ── package (half/full day) ─────────────────────────────────
    elif model == BillingModel.package.value:
        half_h = int(extras.get("half_day_hours", 4))
        full_h = int(extras.get("full_day_hours", 8))
        half_rate = _dec(extras["half_day_rate"]) if "half_day_rate" in extras else _q(daily_rate / 2)
        full_rate = _dec(extras["full_day_rate"]) if "full_day_rate" in extras else daily_rate
        hours = elapsed_seconds / 3600
        if hours <= half_h:
            base_charge = _q(half_rate)
            lines.append(PricingLine("Half-day package",
                                     f"up to {half_h}h", base_charge))
        elif hours <= full_h:
            base_charge = _q(full_rate)
            lines.append(PricingLine("Full-day package",
                                     f"up to {full_h}h", base_charge))
        else:
            extra_hours = math.ceil((elapsed_seconds - full_h * 3600) / 3600)
            base_charge = _q(full_rate)
            overtime_charge = _q(per_hour * extra_hours)
            lines.append(PricingLine("Full-day package",
                                     f"up to {full_h}h", base_charge))
            lines.append(PricingLine("Extra hours",
                                     f"{extra_hours} hr(s)", overtime_charge))

    # ── fixed_route ─────────────────────────────────────────────
    elif model == BillingModel.fixed_route.value:
        route_rates = extras.get("route_rates") or {}
        rate = None
        label = "standard route"
        if route_key and route_key in route_rates:
            rate = _dec(route_rates[route_key])
            label = route_key
        elif "fixed_rate" in extras:
            rate = _dec(extras["fixed_rate"])
        if rate is None:
            raise ValueError(
                f"No fixed rate configured for route '{route_key or '(none)'}'.")
        base_charge = _q(rate)
        lines.append(PricingLine(f"{definition.display_name} ({label})",
                                 "flat rate", base_charge))

    # ── distance_time ───────────────────────────────────────────
    elif model == BillingModel.distance_time.value:
        if "per_km" not in extras:
            raise ValueError("distance_time requires rate_extras.per_km")
        per_km = _dec(extras["per_km"])
        per_min = _dec(extras["per_min"]) if "per_min" in extras else ZERO
        base_fare = _dec(extras["base_fare"]) if "base_fare" in extras else ZERO
        if distance_km is None:
            raise ValueError("distance_time requires distance_km.")
        minutes = math.ceil(elapsed_seconds / 60)
        base_charge = _q(base_fare + (per_km * Decimal(distance_km))
                         + (per_min * minutes))
        lines.append(PricingLine(
            f"{definition.display_name} (metered)",
            f"{distance_km} km + {minutes} min", base_charge))

    # ── route_stops (parked) ────────────────────────────────────
    elif model == BillingModel.route_stops.value:
        if "per_stop_rate" not in extras or stops is None:
            raise ValueError("route_stops requires per_stop_rate and stops.")
        base_charge = _q(_dec(extras["per_stop_rate"]) * stops)
        lines.append(PricingLine(f"{definition.display_name}",
                                 f"{stops} stop(s)", base_charge))

    else:
        raise ValueError(f"Unknown billing model '{model}'.")

    # ── Driver fee stack (rolling + event only) ─────────────────
    driver_daily = driver_ot = driver_accom = ZERO
    if model in (BillingModel.rolling_24h.value, BillingModel.event_base.value):
        if driver_daily_fee is not None:
            driver_daily = _q(Decimal(driver_daily_fee) * max(1, included_days))
            lines.append(PricingLine("Driver fee",
                                     f"{max(1, included_days)} day(s)", driver_daily))
        if driver_overtime_hourly_fee is not None and extra_hours:
            driver_ot = _q(Decimal(driver_overtime_hourly_fee) * extra_hours)
            lines.append(PricingLine("Driver overtime",
                                     f"{extra_hours} hr(s)", driver_ot))
        nights = max(0, included_days - 1)
        if driver_night_accommodation_fee is not None and nights:
            driver_accom = _q(Decimal(driver_night_accommodation_fee) * nights)
            lines.append(PricingLine("Driver accommodation",
                                     f"{nights} night(s)", driver_accom))
    driver_charge = driver_daily + driver_ot + driver_accom

    total = _q(base_charge + overtime_charge + driver_charge)

    return PricingResult(
        service_type=resolve_key(service_type),
        service_label=definition.display_name,
        billing_model=model,
        pickup_at=pickup_at,
        return_at=return_at,
        daily_rate=_q(daily_rate),
        day_hours=day_hours,
        grace_minutes=grace_minutes,
        overtime_hourly_rate=_q(per_hour),
        included_days=included_days,
        extra_hours=extra_hours,
        grace_used_minutes=int(grace_used_seconds // 60),
        base_charge=base_charge,
        overtime_charge=overtime_charge,
        overtime_waivable=overtime_waivable,
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
        ServicePricingConfig.service_type == resolve_key(service_type),
        ServicePricingConfig.is_active.is_(True),
    )
    return (await db.execute(stmt)).scalars().first()


def snapshot_fields(config: Optional[ServicePricingConfig], service_type: str) -> dict:
    definition = get_service(service_type)
    return {
        "pricing_day_hours": (
            config.day_hours if config else definition.base_hours or 24
        ),
        "pricing_grace_minutes": (
            config.grace_minutes if config
            else DEFAULT_GRACE_MINUTES.get(definition.billing_model.value, 0)
        ),
        "pricing_overtime_hourly_rate": config.overtime_hourly_rate if config else None,
    }


async def price_booking(
    db: AsyncSession, booking, daily_rate: Decimal,
    distance_km: Optional[Decimal] = None,
    route_key: Optional[str] = None,
    stops: Optional[int] = None,
) -> PricingResult:
    """
    Price a booking. Priority: booking snapshot → tenant config → catalog defaults.
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
        billing_model=config.billing_model if config else None,
        day_hours=booking.pricing_day_hours or snap["pricing_day_hours"],
        grace_minutes=booking.pricing_grace_minutes or snap["pricing_grace_minutes"],
        overtime_hourly_rate=booking.pricing_overtime_hourly_rate
        or snap["pricing_overtime_hourly_rate"],
        cap_overtime_at_day_rate=config.overtime_cap_at_day_rate if config else True,
        driver_daily_fee=config.driver_daily_fee if config else None,
        driver_overtime_hourly_fee=config.driver_overtime_hourly_fee if config else None,
        driver_night_accommodation_fee=config.driver_night_accommodation_fee if config else None,
        rate_extras=config.rate_extras if config else None,
        distance_km=distance_km,
        route_key=route_key,
        stops=stops,
    )
