"""
Airport Transfer Pricing Engine — Pure, deterministic, no DB.

✅ DESIGN:
  - v1 Logic: Total = Vehicle Base Rate + Toll Fees + Airport Parking Fees.
  - Pure function: Takes raw Decimal inputs, returns a structured quote.
  - No database calls: The caller (router/service) is responsible for fetching 
    the vehicle's base rate and the transfer's add-on fees.
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
class AirportTransferQuote:
    """Immutable pricing result for airport transfer bookings."""
    base_rate: Decimal
    toll_fees: Decimal
    parking_fees: Decimal
    vehicle_subtotal: Decimal
    add_ons_subtotal: Decimal
    total: Decimal
    lines: List[PricingLine] = field(default_factory=list)


def quote_airport_transfer(
    base_rate: Decimal,
    toll_fees: Optional[Decimal] = None,
    parking_fees: Optional[Decimal] = None,
) -> AirportTransferQuote:
    """
    Calculate airport transfer quote.
    
    Args:
        base_rate: The vehicle's all-inclusive airport transfer base rate.
        toll_fees: Optional extra toll fees for this specific trip.
        parking_fees: Optional airport parking fees for this specific trip.
    
    Returns:
        AirportTransferQuote with full breakdown
    
    Raises:
        ValueError: If base_rate is negative, or add-ons are negative.
    """
    base_rate = _q(Decimal(base_rate))
    if base_rate < 0:
        raise ValueError("base_rate cannot be negative")

    toll_fees = _q(Decimal(toll_fees)) if toll_fees else Decimal("0.00")
    if toll_fees < 0:
        raise ValueError("toll_fees cannot be negative")

    parking_fees = _q(Decimal(parking_fees)) if parking_fees else Decimal("0.00")
    if parking_fees < 0:
        raise ValueError("parking_fees cannot be negative")

    # Build line items
    lines = [
        PricingLine(
            description="Airport Transfer Base Fare (Vehicle + Driver + Fuel)",
            quantity="1 trip",
            amount=base_rate
        )
    ]

    add_ons_subtotal = Decimal("0.00")
    
    if toll_fees > 0:
        lines.append(
            PricingLine(
                description="Extra Toll Fees",
                quantity="1 trip",
                amount=toll_fees
            )
        )
        add_ons_subtotal += toll_fees

    if parking_fees > 0:
        lines.append(
            PricingLine(
                description="Airport Parking Fees",
                quantity="1 trip",
                amount=parking_fees
            )
        )
        add_ons_subtotal += parking_fees

    add_ons_subtotal = _q(add_ons_subtotal)
    total = _q(base_rate + add_ons_subtotal)

    return AirportTransferQuote(
        base_rate=base_rate,
        toll_fees=toll_fees,
        parking_fees=parking_fees,
        vehicle_subtotal=base_rate,
        add_ons_subtotal=add_ons_subtotal,
        total=total,
        lines=lines,
    )
