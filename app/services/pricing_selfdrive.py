"""
Self-Drive Pricing Engine — Pure, deterministic, no DB.

Rules:
  - 1 day = 24 hours
  - Minimum 1 day
  - Duration rounded UP: 30min→1d, 24h→1d, 24h01m→2d, 47h→2d, 49h→3d
  - Driver optional: adds driver_daily_fee × days
  - No overtime, no grace, no hourly proration
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional


CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize to 2 decimal places with banker's rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PricingLine:
    """Single line item in the pricing breakdown."""
    description: str
    quantity: str
    amount: Decimal


@dataclass
class SelfDriveQuote:
    """Immutable pricing result for self-drive bookings."""
    pickup_at: datetime
    return_at: datetime
    daily_rate: Decimal
    driver_daily_fee: Optional[Decimal]
    billable_days: int
    vehicle_subtotal: Decimal
    driver_subtotal: Decimal
    total: Decimal
    lines: List[PricingLine] = field(default_factory=list)


def compute_billable_days(pickup_at: datetime, return_at: datetime) -> int:
    """
    Compute billable days for self-drive rental.
    
    Args:
        pickup_at: Start datetime (timezone-aware)
        return_at: End datetime (timezone-aware, must be > pickup_at)
    
    Returns:
        Integer number of billable days (minimum 1)
    
    Raises:
        ValueError: If return_at <= pickup_at
    """
    if return_at <= pickup_at:
        raise ValueError("return_at must be strictly after pickup_at")
    
    elapsed_seconds = (return_at - pickup_at).total_seconds()
    day_seconds = 24 * 3600
    
    # Round UP to nearest day, minimum 1
    return max(1, math.ceil(elapsed_seconds / day_seconds))


def quote_selfdrive(
    pickup_at: datetime,
    return_at: datetime,
    daily_rate: Decimal,
    driver_daily_fee: Optional[Decimal] = None,
) -> SelfDriveQuote:
    """
    Calculate self-drive rental quote.
    
    Args:
        pickup_at: Start datetime
        return_at: End datetime
        daily_rate: Vehicle daily rate (Decimal)
        driver_daily_fee: Optional driver daily fee (Decimal or None)
    
    Returns:
        SelfDriveQuote with full breakdown
    
    Raises:
        ValueError: If return_at <= pickup_at or daily_rate < 0
    """
    daily_rate = Decimal(daily_rate)
    if daily_rate < 0:
        raise ValueError("daily_rate cannot be negative")
    
    billable_days = compute_billable_days(pickup_at, return_at)
    
    # Vehicle subtotal
    vehicle_subtotal = _q(daily_rate * billable_days)
    lines = [
        PricingLine(
            description="Vehicle rental",
            quantity=f"{billable_days} day(s)",
            amount=vehicle_subtotal
        )
    ]
    
    # Driver subtotal (optional)
    driver_subtotal = Decimal("0.00")
    if driver_daily_fee is not None:
        driver_daily_fee = Decimal(driver_daily_fee)
        if driver_daily_fee < 0:
            raise ValueError("driver_daily_fee cannot be negative")
        driver_subtotal = _q(driver_daily_fee * billable_days)
        lines.append(
            PricingLine(
                description="Driver fee",
                quantity=f"{billable_days} day(s)",
                amount=driver_subtotal
            )
        )
    
    total = _q(vehicle_subtotal + driver_subtotal)
    
    return SelfDriveQuote(
        pickup_at=pickup_at,
        return_at=return_at,
        daily_rate=_q(daily_rate),
        driver_daily_fee=_q(driver_daily_fee) if driver_daily_fee else None,
        billable_days=billable_days,
        vehicle_subtotal=vehicle_subtotal,
        driver_subtotal=driver_subtotal,
        total=total,
        lines=lines,
    )
