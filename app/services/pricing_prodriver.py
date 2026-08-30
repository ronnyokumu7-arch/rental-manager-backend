"""
Pro Driver (Chauffeur) Pricing Engine — Pure, deterministic, no DB.

✅ DESIGN:
  - v1 Logic: Total = 12H Base Package (Driver + Vehicle) + Add-ons.
  - Add-ons: Extra hours (overtime), Accommodation (night trips), Tolls, Parking.
  - Pure function: Takes raw Decimal inputs, returns a structured quote.
  - No database calls: The caller (router/service) fetches the driver's fees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
class ProDriverQuote:
    """Immutable pricing result for Pro Driver/Chauffeur bookings."""
    base_rate: Decimal
    extra_hours: int
    overtime_hourly_rate: Decimal
    extra_hours_subtotal: Decimal
    add_ons_subtotal: Decimal
    total: Decimal
    lines: List[PricingLine] = field(default_factory=list)


def quote_prodriver(
    base_rate: Decimal,
    overtime_hourly_rate: Decimal,
    extra_hours: Optional[int] = None,
    accommodation_fee: Optional[Decimal] = None,
    toll_fees: Optional[Decimal] = None,
    parking_fees: Optional[Decimal] = None,
) -> ProDriverQuote:
    """
    Calculate Pro Driver (Chauffeur) quote.
    
    Args:
        base_rate: The 12-hour package rate (Driver fee + Vehicle rate).
        overtime_hourly_rate: Rate charged for every hour beyond the 12H package.
        extra_hours: Number of hours beyond the 12H package.
        accommodation_fee: Optional fee for overnight trips (driver stay).
        toll_fees: Optional toll fees for the route.
        parking_fees: Optional parking fees.
    
    Returns:
        ProDriverQuote with full breakdown
    
    Raises:
        ValueError: If any rate or fee is negative.
    """
    base_rate = _q(Decimal(base_rate))
    if base_rate < 0:
        raise ValueError("base_rate cannot be negative")

    overtime_hourly_rate = _q(Decimal(overtime_hourly_rate))
    if overtime_hourly_rate < 0:
        raise ValueError("overtime_hourly_rate cannot be negative")

    extra_hours = int(extra_hours or 0)
    if extra_hours < 0:
        raise ValueError("extra_hours cannot be negative")

    # Calculate extra hours cost
    extra_hours_subtotal = _q(Decimal(extra_hours) * overtime_hourly_rate)

    # Build line items
    lines = [
        PricingLine(
            description="Pro Driver Package (12 Hours: Chauffeur + Vehicle)",
            quantity="1 package",
            amount=base_rate
        )
    ]

    if extra_hours > 0:
        lines.append(
            PricingLine(
                description="Overtime / Extra Hours",
                quantity=f"{extra_hours} hour(s)",
                amount=extra_hours_subtotal
            )
        )

    add_ons_subtotal = Decimal("0.00")
    
    add_on_map = {
        "Driver Accommodation Fee": accommodation_fee,
        "Toll Fees": toll_fees,
        "Parking Fees": parking_fees,
    }

    for description, fee in add_on_map.items():
        fee_dec = _q(Decimal(fee)) if fee else Decimal("0.00")
        if fee_dec < 0:
            raise ValueError(f"{description} cannot be negative")
        
        if fee_dec > 0:
            lines.append(
                PricingLine(
                    description=description,
                    quantity="1 trip",
                    amount=fee_dec
                )
            )
            add_ons_subtotal += fee_dec

    add_ons_subtotal = _q(add_ons_subtotal)
    total = _q(base_rate + extra_hours_subtotal + add_ons_subtotal)

    return ProDriverQuote(
        base_rate=base_rate,
        extra_hours=extra_hours,
        overtime_hourly_rate=overtime_hourly_rate,
        extra_hours_subtotal=extra_hours_subtotal,
        add_ons_subtotal=add_ons_subtotal,
        total=total,
        lines=lines,
    )
