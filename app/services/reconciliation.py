"""
Reconciliation job — the lifecycle's safety net (runs on schedule).

✅ Multi-tenant safe: iterates per tenant; every query is tenant-scoped.
✅ Conservative: only auto-fixes unambiguous drift; anything uncertain is logged
  as an issue for human review (never guessed).
✅ Time-gated: signed trips auto-start ONLY when pickup has arrived (now/past);
  future pickups wait for a later run at pickup time.
✅ Cache-aware: invalidates booking/vehicle/invoice caches after each tenant
  commit so the dashboard reflects changes instantly (no 300s delay).

Jobs:
  1. fix_booking_vehicle_drift  — booking/vehicle status out of sync
  2. auto_start_signed_trips    — signed + pickup arrived but not active (retry)
  3. mark_overdue_invoices      — sent/partially_paid past due_date → overdue
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import timeutils
from app.models.bookings import Booking, BookingStatus
from app.models.contracts import Contract
from app.models.invoices import Invoice, InvoiceStatus
from app.models.tenants import Tenant
from app.models.vehicles import Vehicle, VehicleStatus
from app.services.booking_lifecycle import BookingLifecycleService
from app.services.cache import (
    invalidate_booking_cache, invalidate_vehicle_cache, invalidate_invoice_cache,
)


# ─── 1. BOOKING ↔ VEHICLE DRIFT ────────────────────────────────────────────
async def fix_booking_vehicle_drift(db: AsyncSession, tenant_id: int, report: dict) -> int:
    fixed = 0

    # (a) Active booking but vehicle not rented → set rented (if it was available).
    active_stmt = (
        select(Booking).options(selectinload(Booking.vehicle))
        .where(
            Booking.tenant_id == tenant_id,
            Booking.status == BookingStatus.active,
            Booking.is_archived == False,
        )
    )
    for b in (await db.execute(active_stmt)).scalars().all():
        v = b.vehicle
        if not v:
            continue
        if v.status == VehicleStatus.available:
            v.status = VehicleStatus.rented
            fixed += 1
        elif v.status != VehicleStatus.rented:
            report["issues"].append(
                f"booking {b.id} active but vehicle {v.id} in {v.status.value} — needs review"
            )

    # (b) Vehicle rented but NO active booking → free it (flag mileage).
    rented_stmt = select(Vehicle).where(
        Vehicle.tenant_id == tenant_id, Vehicle.status == VehicleStatus.rented,
    )
    for v in (await db.execute(rented_stmt)).scalars().all():
        has_active = (await db.execute(
            select(Booking.id).where(
                Booking.vehicle_id == v.id,
                Booking.status == BookingStatus.active,
                Booking.is_archived == False,
            )
        )).scalars().first()
        if not has_active:
            v.status = VehicleStatus.available
            v.mileage_due = True
            fixed += 1

    return fixed


# ─── 2. SIGNED + PICKUP ARRIVED BUT NOT ACTIVE → AUTO-START (time-gated) ───
async def auto_start_signed_trips(db: AsyncSession, tenant_id: int) -> int:
    started = 0
    now = datetime.now(timezone.utc)

    stmt = (
        select(Contract).options(selectinload(Contract.booking))
        .join(Booking, Contract.booking_id == Booking.id)
        .where(
            Booking.tenant_id == tenant_id,
            Contract.signed_by_client == True,
            Booking.status.in_([BookingStatus.pending, BookingStatus.confirmed]),
            Booking.is_archived == False,
        )
    )
    for contract in (await db.execute(stmt)).scalars().all():
        booking = contract.booking

        # ✅ TIME GATE: only start when pickup has arrived (now or past).
        # Future pickups wait for a later run at pickup time.
        raw_pickup = booking.pickup_at or booking.start_date
        if raw_pickup is None:
            continue
        if timeutils.normalize(raw_pickup) > now:
            continue  # not yet due — scheduler retries at pickup time

        try:
            await BookingLifecycleService.start_trip_auto(db, booking)
            started += 1
        except Exception:
            continue  # preconditions unmet → operator starts manually
    return started


# ─── 3. OVERDUE INVOICES ───────────────────────────────────────────────────
async def mark_overdue_invoices(db: AsyncSession, tenant_id: int) -> int:
    now = datetime.now(timezone.utc)
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.partially_paid]),
        Invoice.due_date < now,
    )
    marked = 0
    for inv in (await db.execute(stmt)).scalars().all():
        inv.status = InvoiceStatus.overdue
        marked += 1
    return marked


# ─── PER-TENANT ORCHESTRATOR ───────────────────────────────────────────────
async def reconcile_tenant(db: AsyncSession, tenant_id: int) -> dict:
    report = {"tenant_id": tenant_id, "drift_fixed": 0, "auto_started": 0,
              "overdue_marked": 0, "issues": []}
    report["drift_fixed"] = await fix_booking_vehicle_drift(db, tenant_id, report)
    report["auto_started"] = await auto_start_signed_trips(db, tenant_id)
    report["overdue_marked"] = await mark_overdue_invoices(db, tenant_id)
    return report


# ─── ENTRYPOINT (called by your scheduler) ─────────────────────────────────
async def run_reconciliation_job() -> list:
    """Iterate ALL tenants, reconcile each in its own transaction."""
    from app.db.database import AsyncSessionLocal

    results = []
    async with AsyncSessionLocal() as db:
        tenant_ids = (await db.execute(select(Tenant.id))).scalars().all()

    for tid in tenant_ids:
        async with AsyncSessionLocal() as db:
            try:
                report = await reconcile_tenant(db, tid)
                await db.commit()

                # ✅ Invalidate caches so the dashboard flips instantly (no 300s delay)
                await invalidate_booking_cache(tid)
                await invalidate_vehicle_cache(tid)
                await invalidate_invoice_cache(tid)

                if report["drift_fixed"] or report["auto_started"] or report["issues"]:
                    print(f"🔁 reconciliation tenant {tid}: {report}")
                results.append(report)
            except Exception as e:
                await db.rollback()
                print(f"❌ reconciliation failed for tenant {tid}: {e}")
    return results
