# app/services/booking_factory.py
"""
✅ BOOKING FACTORY — single source of truth for schedule, pricing, and changes.

Modes:
  - quote_new    : dry-run pricing for a new booking (no writes)
  - create       : commit mode (booking + quotation born atomically)
  - quote_change : dry-run extend / reduce / reschedule with delta (no writes)
  - apply_change : commit mode for changes (recompute-diff, invoice sync, log)

Pricing is ALWAYS `vehicle rate × billable days` via the pure engines.
Changes use recompute-and-diff: delta = quote(new) − quote(old), applied on
top of the current total so manual adjustments are never erased.
Day-only changes are exact: ceil is additive over whole days.
✅ BUSINESS RULE: extensions/reductions are by whole days ONLY (return clock
   time must stay the same). Hourly changes are a future bridge.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutils
from app.models.bookings import Booking, BookingStatus
from app.models.clients import Client, ClientStatus
from app.models.drivers import Driver, DriverStatus
from app.models.invoices import Invoice
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.schemas.booking import BookingCreate
from app.services.activity_log import ActivityLogService
from app.services.booking_tasks import BookingTaskService
from app.services.cache import invalidate_booking_cache
from app.services.invoices import create_quotation_for_booking
from app.services.number_generator import generate_booking_number
from app.services.pricing_airport import quote_airport_transfer
from app.services.pricing_prodriver import quote_prodriver
from app.services.pricing_selfdrive import quote_selfdrive
from app.services.pricing_wedding import quote_wedding
from app.services.activity_logs.booking import BookingActivityLogger
from app.services.activity_logs.client import ClientActivityLogger

SELFDRIVE = "selfdrive"
AIRPORT_TRANSFER = "airport_transfer"
WEDDING = "wedding"
PRO_DRIVER = "pro_driver"

IMMUTABLE_STATUSES = {BookingStatus.completed, BookingStatus.cancelled}
LIVE_STATUSES = [BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active]


# =============================================================================
# INTERNAL HELPERS
# =============================================================================
def _lines_payload(quote) -> list:
    return [
        {"description": l.description, "quantity": l.quantity, "amount": l.amount}
        for l in getattr(quote, "lines", [])
    ]


async def _load_vehicle(db: AsyncSession, tenant_id: int, vehicle_id: int) -> Vehicle:
    vehicle = (await db.execute(select(Vehicle).where(
        Vehicle.id == vehicle_id, Vehicle.tenant_id == tenant_id,
    ))).scalars().first()
    if not vehicle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
    if vehicle.status != VehicleStatus.available or vehicle.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Vehicle is not available.")
    return vehicle


async def load_driver_assignment(db: AsyncSession, tenant_id: int, driver_id: Optional[int]) -> Optional[Driver]:
    """Tenant-scoped, not archived, not suspended. (Lifted from router.)"""
    if driver_id is None:
        return None
    driver = (await db.execute(select(Driver).where(
        Driver.id == driver_id, Driver.tenant_id == tenant_id,
    ))).scalars().first()
    if not driver:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
    if driver.is_archived:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Driver is archived and cannot be assigned.")
    if driver.status == DriverStatus.suspended:
        raise HTTPException(status.HTTP_409_CONFLICT, "Driver is suspended and cannot be assigned.")
    return driver


async def _assert_vehicle_free(
    db: AsyncSession, *, tenant_id: int, vehicle_id: int,
    pickup: datetime, ret: datetime, plate: str,
    exclude_booking_id: Optional[int] = None,
) -> None:
    """Time-exact double-booking prevention (lifted from router; reusable for changes)."""
    stmt = select(Booking.id).where(
        Booking.vehicle_id == vehicle_id,
        Booking.tenant_id == tenant_id,
        Booking.is_archived == False,
        Booking.status.in_(LIVE_STATUSES),
        and_(
            func.coalesce(Booking.pickup_at, Booking.start_date) < ret,
            func.coalesce(Booking.scheduled_return_at, Booking.end_date) > pickup,
        ),
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Vehicle {plate} is already booked for these dates.",
        )


def _price(
    *, service_type: str, vehicle: Vehicle, driver: Optional[Driver],
    pickup: datetime, ret: datetime,
    service_details: Optional[Dict[str, Any]], toll_fees: Decimal, parking_fees: Decimal,
) -> Dict[str, Any]:
    """
    Dispatch to the pure engines (lifted verbatim from the router).
    ✅ Rates come ONLY from vehicle/driver config — never from client input.
    """
    if service_type == AIRPORT_TRANSFER:
        if not vehicle.supports_airport_transfer or not vehicle.airport_transfer_base_rate:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Vehicle does not support airport transfers or has no base rate configured.")
        try:
            quote = quote_airport_transfer(
                base_rate=Decimal(vehicle.airport_transfer_base_rate),
                toll_fees=Decimal(toll_fees), parking_fees=Decimal(parking_fees),
            )
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
        return {"daily_rate": vehicle.airport_transfer_base_rate, "billable_days": 1,
                "computed_total": quote.total, "lines": _lines_payload(quote)}

    if service_type == WEDDING:
        if not vehicle.supports_wedding_service or not vehicle.wedding_base_rate:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Vehicle does not support wedding services or has no base rate configured.")
        details = service_details or {}
        try:
            quote = quote_wedding(
                base_rate=Decimal(vehicle.wedding_base_rate),
                overtime_hourly_rate=Decimal(driver.overtime_hourly_fee if driver and driver.overtime_hourly_fee else 0),
                extra_hours=int(details.get("extra_hours", 0)),
                toll_fees=Decimal(details.get("toll_fees", 0)),
                decoration_fee=Decimal(details.get("decoration_fee", 0)),
                priority_booking_fee=Decimal(details.get("priority_booking_fee", 0)),
                fuel_fee=Decimal(details.get("fuel_fee", 0)),
            )
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
        return {"daily_rate": vehicle.wedding_base_rate, "billable_days": 1,
                "computed_total": quote.total, "lines": _lines_payload(quote)}

    if service_type == PRO_DRIVER:
        if not driver:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Pro Driver (Chauffeur) service requires a staff driver assignment.")
        details = service_details or {}
        base_rate = (Decimal(vehicle.daily_rate) if vehicle.daily_rate else Decimal("0.00")) + \
                    (Decimal(driver.daily_fee) if driver.daily_fee else Decimal("0.00"))
        if base_rate <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Pro Driver base rate cannot be zero. Check vehicle daily rate and driver daily fee.")
        try:
            quote = quote_prodriver(
                base_rate=base_rate,
                overtime_hourly_rate=Decimal(driver.overtime_hourly_fee) if driver.overtime_hourly_fee else Decimal("0.00"),
                extra_hours=int(details.get("extra_hours", 0)),
                accommodation_fee=Decimal(details.get("accommodation_fee", 0)),
                toll_fees=Decimal(details.get("toll_fees", 0)),
                parking_fees=Decimal(details.get("parking_fees", 0)),
            )
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
        return {"daily_rate": base_rate, "billable_days": 1,
                "computed_total": quote.total, "lines": _lines_payload(quote)}

    # ✅ SELF-DRIVE: vehicle rate × days (the business rule, untouched)
    if not vehicle.daily_rate or Decimal(vehicle.daily_rate) <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle has no daily rate configured.")
    try:
        quote = quote_selfdrive(
            pickup_at=pickup, return_at=ret,
            daily_rate=Decimal(vehicle.daily_rate),
            driver_daily_fee=Decimal(driver.daily_fee) if driver and driver.daily_fee else None,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return {"daily_rate": vehicle.daily_rate, "billable_days": quote.billable_days,
            "computed_total": quote.total, "lines": _lines_payload(quote)}


def _quote_payload(service_type, pickup, ret, price) -> Dict[str, Any]:
    return {
        "service_type": service_type,
        "pickup_at": timeutils.to_platform_iso(pickup),
        "scheduled_return_at": timeutils.to_platform_iso(ret),
        "billable_days": price["billable_days"],
        "daily_rate": price["daily_rate"],
        "lines": price["lines"],
        "total": price["computed_total"],
        "currency_code": "KES",
    }


# =============================================================================
# MODE 1: QUOTE (NEW)
# =============================================================================
async def quote_new(
    db: AsyncSession, *, tenant_id: int, vehicle_id: int,
    pickup_raw: Optional[Any], return_raw: Optional[Any],
    service_type: str = SELFDRIVE, driver_id: Optional[int] = None,
    service_details: Optional[Dict[str, Any]] = None,
    toll_fees: Decimal = Decimal("0"), parking_fees: Decimal = Decimal("0"),
) -> Dict[str, Any]:
    """Dry-run pricing with defaults (pickup=now, return=+1d) and conflict check."""
    vehicle = await _load_vehicle(db, tenant_id, vehicle_id)
    driver = await load_driver_assignment(db, tenant_id, driver_id)

    pickup, ret = timeutils.resolve_schedule(pickup_raw, return_raw)
    try:
        timeutils.validate_new_schedule(pickup, ret)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    await _assert_vehicle_free(db, tenant_id=tenant_id, vehicle_id=vehicle_id,
                               pickup=pickup, ret=ret, plate=vehicle.plate_number)

    price = _price(service_type=service_type, vehicle=vehicle, driver=driver,
                   pickup=pickup, ret=ret, service_details=service_details,
                   toll_fees=toll_fees, parking_fees=parking_fees)
    return _quote_payload(service_type, pickup, ret, price)


# =============================================================================
# MODE 2: CREATE (COMMIT)
# =============================================================================
async def create_booking(db: AsyncSession, intent: BookingCreate, user: User) -> Booking:
    """Full atomic create: validate → schedule → price → persist → quotation → tasks/logs."""
    # 1. Client (lifted)
    client = (await db.execute(select(Client).where(
        Client.id == intent.client_id, Client.tenant_id == user.tenant_id,
    ))).scalars().first()
    if not client:
        raise HTTPException(404, "Client not found.")
    if client.status == ClientStatus.suspended or client.is_archived:
        raise HTTPException(400, "Client cannot make bookings.")

    # 2. Vehicle + driver
    vehicle = await _load_vehicle(db, user.tenant_id, intent.vehicle_id)
    driver = await load_driver_assignment(db, user.tenant_id, intent.driver_id)

    # 3. ✅ Schedule: exact > legacy > defaults; aware-only validation
    pickup, ret = timeutils.resolve_schedule(
        intent.pickup_at or intent.start_date,
        intent.scheduled_return_at or intent.end_date,
    )
    try:
        timeutils.validate_new_schedule(pickup, ret)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    await _assert_vehicle_free(db, tenant_id=user.tenant_id, vehicle_id=vehicle.id,
                               pickup=pickup, ret=ret, plate=vehicle.plate_number)

    # 4. ✅ Price (server is source of truth)
    price = _price(service_type=intent.service_type, vehicle=vehicle, driver=driver,
                   pickup=pickup, ret=ret, service_details=intent.service_details,
                   toll_fees=intent.toll_fees, parking_fees=intent.parking_fees)

    # 5. Booking number + persist (both datetime pairs mirrored)
    booking_number = await generate_booking_number(db, user.tenant_id)
    db_booking = Booking(
        client_id=client.id, vehicle_id=vehicle.id,
        destination=intent.destination,
        pickup_location=intent.pickup_location, return_location=intent.return_location,
        start_date=pickup, end_date=ret,
        pickup_at=pickup, scheduled_return_at=ret,
        service_type=intent.service_type, service_details=intent.service_details,
        driver_id=driver.id if driver else None,
        toll_fees=intent.toll_fees, parking_fees=intent.parking_fees,
        daily_rate=price["daily_rate"], billable_days=price["billable_days"],
        computed_total=price["computed_total"], total_amount=price["computed_total"],
        manually_adjusted=False, price_note=None,
        currency_code=intent.currency_code or "KES",
        tenant_id=user.tenant_id, status=BookingStatus.pending,
        booking_number=booking_number,
    )
    db.add(db_booking)
    await db.flush()

    # 6. Quotation born with the booking (atomic)
    await create_quotation_for_booking(db_booking, db)
    await db.commit()
    await db.refresh(db_booking)

    # 7. Tasks + activity logs (non-blocking; lifted)
    try:
        await BookingTaskService.on_booking_created(db, db_booking, client.full_name, vehicle.plate_number)
    except Exception as e:
        print(f"⚠️ Warning: Failed to create tasks for booking {db_booking.id}: {e}")
    try:
        await BookingActivityLogger.on_created(
            db=db, tenant_id=user.tenant_id, user_id=user.id, booking=db_booking,
            client_name=client.full_name, client=client, vehicle=vehicle,
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking creation: {e}")
    try:
        await ClientActivityLogger.on_created(db=db, tenant_id=user.tenant_id, user_id=user.id, client=client)
    except Exception as e:
        print(f"⚠️ Warning: Failed to log client creation: {e}")
    await db.commit()

    await invalidate_booking_cache(user.tenant_id)

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Booking).options(
            selectinload(Booking.client), selectinload(Booking.vehicle), selectinload(Booking.driver),
        ).where(Booking.id == db_booking.id)
    )
    return result.scalars().first()


# =============================================================================
# MODE 3 & 4: CHANGE (QUOTE + APPLY)
# =============================================================================
def _classify(old_p, old_r, new_p, new_r) -> str:
    p_moved, r_moved = new_p != old_p, new_r != old_r
    if p_moved:
        return "reschedule"
    if r_moved:
        return "extend" if new_r > old_r else "reduce"
    return "noop"


def _same_platform_clock(a: datetime, b: datetime) -> bool:
    """
    ✅ DAY-ONLY RULE: for extend/reduce the return clock time (hour:minute in
    platform time) must stay the same — only the date moves.
    """
    a_local = a.astimezone(timeutils.PLATFORM_TZ)
    b_local = b.astimezone(timeutils.PLATFORM_TZ)
    return (a_local.hour, a_local.minute) == (b_local.hour, b_local.minute)


def _guard_change(booking: Booking, kind: str, old_p: datetime, new_p: datetime, new_r: datetime) -> None:
    now = timeutils.now_utc()
    if booking.status in IMMUTABLE_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Booking is {booking.status.value} and can no longer be changed.")
    if kind == "noop":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No change supplied.")
    # ✅ Overdue-active guard: an active trip can't be changed to a past return
    if booking.status == BookingStatus.active and kind in ("extend", "reduce") and new_r < now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Trip already started — new return cannot be in the past.")
    if kind == "reschedule":
        if booking.status == BookingStatus.active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Trip already started — only extensions or reductions are allowed.")
        if old_p <= now:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Pickup time has passed — booking can no longer be rescheduled.")
        if new_p < now - timeutils.PAST_GRACE:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "New pickup time cannot be in the past.")


async def _driver_fee_for(db: AsyncSession, booking: Booking) -> Optional[Decimal]:
    if not booking.driver_id:
        return None
    driver = (await db.execute(select(Driver).where(Driver.id == booking.driver_id))).scalars().first()
    return Decimal(driver.daily_fee) if driver and driver.daily_fee else None


async def _reprice_change(db: AsyncSession, booking: Booking, new_p: datetime, new_r: datetime):
    """Recompute-diff on the rate locked at creation. Non-selfdrive → delta 0."""
    old_p = timeutils.normalize(booking.pickup_at or booking.start_date)
    old_r = timeutils.normalize(booking.scheduled_return_at or booking.end_date)

    if booking.service_type != SELFDRIVE:
        return {"new_days": booking.billable_days or 1,
                "new_engine_total": booking.computed_total or booking.total_amount,
                "delta": Decimal("0"), "lines": []}

    rate = Decimal(booking.daily_rate) if booking.daily_rate else None
    if not rate:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Booking has no locked daily rate.")
    fee = await _driver_fee_for(db, booking)

    try:
        old_quote = quote_selfdrive(pickup_at=old_p, return_at=old_r, daily_rate=rate, driver_daily_fee=fee)
        new_quote = quote_selfdrive(pickup_at=new_p, return_at=new_r, daily_rate=rate, driver_daily_fee=fee)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    baseline = booking.computed_total if booking.computed_total is not None else old_quote.total
    delta = new_quote.total - Decimal(baseline)
    return {"new_days": new_quote.billable_days, "new_engine_total": new_quote.total,
            "delta": delta, "lines": _lines_payload(new_quote)}


async def quote_change(
    db: AsyncSession, booking: Booking, *,
    new_pickup_raw: Optional[Any] = None, new_return_raw: Optional[Any] = None,
) -> Dict[str, Any]:
    """Dry-run change: classify → guard → day-only check → conflict-check → recompute-diff."""
    old_p = timeutils.normalize(booking.pickup_at or booking.start_date)
    old_r = timeutils.normalize(booking.scheduled_return_at or booking.end_date)
    new_p = timeutils.parse_datetime(new_pickup_raw, field_name="new_pickup_at") if new_pickup_raw else old_p
    new_r = timeutils.parse_datetime(new_return_raw, field_name="new_return_at") if new_return_raw else old_r

    kind = _classify(old_p, old_r, new_p, new_r)

    # ✅ BUSINESS RULE: extend/reduce are by whole days ONLY.
    # The return date may move; the return clock time must stay the same.
    if kind in ("extend", "reduce") and not _same_platform_clock(old_r, new_r):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Extensions and reductions are by whole days only. "
            "Keep the return time the same and change only the return date.",
        )

    _guard_change(booking, kind, old_p, new_p, new_r)
    try:
        timeutils.validate_order(new_p, new_r)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == booking.vehicle_id))).scalars().first()
    await _assert_vehicle_free(db, tenant_id=booking.tenant_id, vehicle_id=booking.vehicle_id,
                               pickup=new_p, ret=new_r,
                               plate=vehicle.plate_number if vehicle else str(booking.vehicle_id),
                               exclude_booking_id=booking.id)

    re = await _reprice_change(db, booking, new_p, new_r)
    current_total = Decimal(booking.total_amount)
    delta = re["delta"]
    return {
        "kind": kind,
        "current": {
            "pickup_at": timeutils.to_platform_iso(old_p),
            "scheduled_return_at": timeutils.to_platform_iso(old_r),
            "billable_days": booking.billable_days,
            "total": current_total,
        },
        "new": {
            "pickup_at": timeutils.to_platform_iso(new_p),
            "scheduled_return_at": timeutils.to_platform_iso(new_r),
            "billable_days": re["new_days"],
            "total": re["new_engine_total"],
            "lines": re["lines"],
        },
        "delta_days": (re["new_days"] or 0) - (booking.billable_days or 0),
        "delta_amount": delta,
        "direction": "charge" if delta > 0 else ("credit" if delta < 0 else "none"),
        "new_total": current_total + delta,
        "currency_code": booking.currency_code or "KES",
    }


async def apply_change(
    db: AsyncSession, booking: Booking, *, user: User,
    new_pickup_raw: Optional[Any] = None, new_return_raw: Optional[Any] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit a quoted change: mutate snapshot, sync invoice document, log, invalidate."""
    payload = await quote_change(db, booking, new_pickup_raw=new_pickup_raw, new_return_raw=new_return_raw)

    old_r = timeutils.normalize(booking.scheduled_return_at or booking.end_date)
    new_p = timeutils.parse_datetime(payload["new"]["pickup_at"])
    new_r = timeutils.parse_datetime(payload["new"]["scheduled_return_at"])

    # ✅ Audit trail: capture the original end on first modification only
    if booking.original_end_date is None and payload["kind"] in ("extend", "reduce"):
        booking.original_end_date = old_r

    booking.pickup_at = new_p
    booking.scheduled_return_at = new_r
    booking.start_date = new_p          # keep legacy mirror in sync (Gantt/availability)
    booking.end_date = new_r
    if booking.service_type == SELFDRIVE:
        booking.billable_days = payload["new"]["billable_days"]
        booking.computed_total = payload["new"]["total"]
    booking.total_amount = payload["new_total"]

    # ✅ Sync whichever document exists (quotation or invoice) so clients see truth
    doc = (await db.execute(
        select(Invoice).where(Invoice.booking_id == booking.id)
        .order_by(Invoice.created_at.desc())
    )).scalars().first()
    if doc:
        doc.amount_due = booking.total_amount
        doc.due_date = new_p

    try:
        await ActivityLogService.log(
            db=db, tenant_id=booking.tenant_id, user_id=user.id,
            action=f"booking_{payload['kind']}", target_type="booking", target_id=booking.id,
            details={"delta_amount": str(payload["delta_amount"]),
                     "new_total": str(payload["new_total"]), "note": note},
        )
    except Exception as e:
        print(f"⚠️ Warning: Failed to log booking change: {e}")

    await db.commit()
    await db.refresh(booking)
    await invalidate_booking_cache(booking.tenant_id)
    return payload
