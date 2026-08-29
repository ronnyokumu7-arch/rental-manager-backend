"""
BookingLifecycleService — SINGLE SOURCE OF TRUTH for booking + vehicle transitions.

✅ DESIGN GUARANTEES:
  - Tenant-scoped: every load verifies booking/vehicle belong to current_user.tenant_id.
  - Row-locked: SELECT ... FOR UPDATE on booking + vehicle kills double-rent races.
  - Idempotent: re-calling a completed transition returns current state, never corrupts.
  - Status-respecting: each transition only fires from its allowed source states.
  - Vehicle sync owned HERE: `rented` is set only by booking transitions, atomically.
  - Commission owned HERE: trial-exempt, rate from PlatformSettings, fires once per trip.
  - ✅ Activity Logs owned HERE: logged BEFORE commit (atomic with the transition,
    relationships still loaded → rich summaries, rows actually persist).
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookings import Booking, BookingStatus, CancellationReason
from app.models.clients import Client, ClientStatus
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.platform_settings import PlatformSettings
from app.models.tenants import Tenant
from app.models.users import User
from app.models.vehicles import Vehicle, VehicleStatus
from app.services.cache import invalidate_booking_cache, invalidate_vehicle_cache

# ✅ NEW: Activity Loggers
from app.services.activity_logs.booking import BookingActivityLogger
from app.services.activity_logs.vehicle import VehicleActivityLogger


def _client_name(booking: Optional[Booking]) -> Optional[str]:
    """✅ SAFE client name read — never lazy-loads (MissingGreenlet-proof)."""
    client = booking.__dict__.get("client") if booking is not None else None
    return client.full_name if client else None


class BookingLifecycleService:
    """All booking + vehicle state transitions live here."""

    # ─── LOCKED LOADERS (tenant-scoped) ────────────────────────────────────
    @staticmethod
    async def _load_booking_locked(
        db: AsyncSession, booking_id: int, tenant_id: int,
    ) -> Booking:
        from sqlalchemy.orm import selectinload
        stmt = (
            select(Booking)
            .options(
                selectinload(Booking.client),
                selectinload(Booking.vehicle),
                selectinload(Booking.driver),   # ✅ FIXED: was missing → MissingGreenlet on serialize
            )
            .where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
            .with_for_update()
        )
        booking = (await db.execute(stmt)).scalars().unique().first()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found.")
        return booking

    @staticmethod
    async def _load_vehicle_locked(
        db: AsyncSession, vehicle_id: int, tenant_id: int,
    ) -> Vehicle:
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
        vehicle = (await db.execute(stmt)).scalars().first()
        if not vehicle or vehicle.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        return vehicle

    @staticmethod
    async def _reload(db: AsyncSession, booking_id: int) -> Booking:
        from sqlalchemy.orm import selectinload
        stmt = (
            select(Booking)
            .options(
                selectinload(Booking.client),
                selectinload(Booking.vehicle),
                selectinload(Booking.driver),
            )
            .where(Booking.id == booking_id)
        )
        return (await db.execute(stmt)).scalars().unique().first()

    @staticmethod
    async def _invalidate(db: AsyncSession, tenant_id: int) -> None:
        await invalidate_booking_cache(tenant_id)
        await invalidate_vehicle_cache(tenant_id)

    # ─── CONFIRM (client-driven via quotation accept; NOT a dashboard button) ──
    @classmethod
    async def confirm(cls, db: AsyncSession, booking_id: int, current_user: User) -> Booking:
        booking = await cls._load_booking_locked(db, booking_id, current_user.tenant_id)

        if booking.status == BookingStatus.confirmed:
            return await cls._reload(db, booking.id)          # idempotent
        if booking.status != BookingStatus.pending:
            raise HTTPException(status_code=400, detail="Only pending bookings can be confirmed.")

        booking.status = BookingStatus.confirmed

        # ✅ Log BEFORE commit: atomic with transition, relationships still loaded
        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                booking=booking,
                old_status="pending",
                new_status="confirmed",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log booking confirmation: {e}")

        await db.commit()
        await cls._invalidate(db, current_user.tenant_id)

        return await cls._reload(db, booking.id)

    # ─── START TRIP (activate) ─────────────────────────────────────────────
    @classmethod
    async def start_trip(cls, db: AsyncSession, booking_id: int, current_user: User) -> Booking:
        booking = await cls._load_booking_locked(db, booking_id, current_user.tenant_id)

        if booking.status == BookingStatus.active:
            return await cls._reload(db, booking.id)          # idempotent
        if booking.status not in (BookingStatus.pending, BookingStatus.confirmed):
            raise HTTPException(status_code=400, detail="Only pending or confirmed bookings can start.")

        # Client must be active
        client = (await db.execute(
            select(Client).where(Client.id == booking.client_id)
        )).scalars().first()
        if not client or client.status != ClientStatus.active:
            raise HTTPException(status_code=400, detail="Client must be active to start a trip.")

        vehicle = await cls._load_vehicle_locked(db, booking.vehicle_id, current_user.tenant_id)
        if vehicle.status != VehicleStatus.available:
            raise HTTPException(status_code=409, detail="Vehicle is not available.")

        old_status = booking.status
        booking.status = BookingStatus.active
        vehicle.status = VehicleStatus.rented   # ✅ owned exclusively by this transition

        # ✅ Commission (trial-exempt, operator-triggered)
        await cls._create_commission_event(db, booking, current_user.tenant_id, current_user.id)

        # ✅ Log BEFORE commit (atomic; rich snapshots)
        try:
            await VehicleActivityLogger.on_rented(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                vehicle=vehicle,
                booking_number=booking.booking_number,
                client_name=_client_name(booking),
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log vehicle rented: {e}")

        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                booking=booking,
                old_status=old_status,
                new_status="active",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log booking start: {e}")

        await db.commit()
        await cls._invalidate(db, current_user.tenant_id)

        return await cls._reload(db, booking.id)

    # ─── COMPLETE (return) ─────────────────────────────────────────────────
    @classmethod
    async def complete(cls, db: AsyncSession, booking_id: int, current_user: User) -> Booking:
        booking = await cls._load_booking_locked(db, booking_id, current_user.tenant_id)

        if booking.status == BookingStatus.completed:
            return await cls._reload(db, booking.id)          # idempotent
        if booking.status != BookingStatus.active:
            raise HTTPException(status_code=400, detail="Only active bookings can be completed.")

        vehicle = await cls._load_vehicle_locked(db, booking.vehicle_id, current_user.tenant_id)

        booking.status = BookingStatus.completed
        booking.actual_return_at = datetime.now(timezone.utc)   # ✅ late-return reconciliation

        # ✅ Vehicle returns to the rentable pool immediately; mileage tracked as a flag.
        vehicle.status = VehicleStatus.available
        vehicle.mileage_due = True

        # ✅ Log BEFORE commit (atomic; rich snapshots)
        try:
            await VehicleActivityLogger.on_returned(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                vehicle=vehicle,
                booking_number=booking.booking_number,
                client_name=_client_name(booking),
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log vehicle returned: {e}")

        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                booking=booking,
                old_status="active",
                new_status="completed",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log booking completion: {e}")

        await db.commit()
        await cls._invalidate(db, current_user.tenant_id)

        return await cls._reload(db, booking.id)

    # ─── CANCEL (with reason) ──────────────────────────────────────────────
    @classmethod
    async def cancel(
        cls,
        db: AsyncSession,
        booking_id: int,
        current_user: User,
        reason: CancellationReason,
        cancelled_by: Optional[int] = None,
    ) -> Booking:
        booking = await cls._load_booking_locked(db, booking_id, current_user.tenant_id)

        if booking.status == BookingStatus.cancelled:
            return await cls._reload(db, booking.id)          # idempotent
        if booking.status == BookingStatus.completed:
            raise HTTPException(status_code=400, detail="Cannot cancel a completed booking.")

        old_status = booking.status
        was_active = booking.status == BookingStatus.active

        booking.status = BookingStatus.cancelled
        booking.cancellation_reason = reason.value          # validated str-enum
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancelled_by = cancelled_by or current_user.id

        if was_active:
            # Vehicle came back mid-trip → free it, flag mileage for logging.
            vehicle = await cls._load_vehicle_locked(db, booking.vehicle_id, current_user.tenant_id)
            vehicle.status = VehicleStatus.available
            vehicle.mileage_due = True

            # ✅ Log BEFORE commit
            try:
                await VehicleActivityLogger.on_returned(
                    db=db,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    vehicle=vehicle,
                    booking_number=booking.booking_number,
                    client_name=_client_name(booking),
                )
            except Exception as e:
                print(f"⚠️ Warning: Failed to log vehicle return on cancel: {e}")

        # ✅ Log BEFORE commit
        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                booking=booking,
                old_status=old_status,
                new_status="cancelled",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log booking cancel: {e}")

        await db.commit()
        await cls._invalidate(db, current_user.tenant_id)

        return await cls._reload(db, booking.id)

    # ─── COMMISSION (fires once per trip — SINGLE SOURCE OF TRUTH) ─────────
    @staticmethod
    async def _create_commission_event(
        db: AsyncSession,
        booking: Booking,
        tenant_id: int,
        created_by: Optional[int],
    ) -> None:
        """
        ✅ TRIAL RULE: trips started during the free trial create NO event —
        the tenant owes nothing and nothing is counted.
        ✅ RATE: read from PlatformSettings (super-admin configurable).
        ✅ booking_id is unique → a trip can never be double-charged.
        """
        tenant = await db.get(Tenant, tenant_id)
        now = datetime.now(timezone.utc)
        in_trial = (
            tenant is not None
            and tenant.trial_ends_at is not None
            and tenant.trial_ends_at > now
        )
        if in_trial:
            return  # trial trips are commission-free

        settings = (
            await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
        ).scalars().first()
        amount = Decimal(settings.commission_amount) if settings else Decimal("150.00")

        db.add(CommissionEvent(
            tenant_id=tenant_id,
            booking_id=booking.id,
            amount=amount,
            currency_code="KES",
            status=CommissionStatus.unpaid,
            created_by=created_by,
        ))

    # ─── CLIENT-DRIVEN (public, no authenticated user) — flush-only ────────
    @classmethod
    async def confirm_client(cls, db: AsyncSession, booking: Booking) -> Booking:
        """Quotation accept ⇒ confirmed. FLUSH only — caller commits atomically.
        Assumes booking already loaded (locked) by the caller."""
        if booking.status == BookingStatus.confirmed:
            return booking
        if booking.status != BookingStatus.pending:
            raise HTTPException(status_code=400, detail="This booking can no longer be confirmed.")
        booking.status = BookingStatus.confirmed

        # ✅ NEW: Log the booking confirmed (system/event driven)
        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=booking.tenant_id,
                user_id=None,
                booking=booking,
                old_status="pending",
                new_status="confirmed",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log client booking confirmation: {e}")

        await db.flush()
        return booking

    @classmethod
    async def cancel_client(
        cls, db: AsyncSession, booking: Booking, reason: CancellationReason,
    ) -> Booking:
        """Client cancel from the public portal. FLUSH only — caller commits."""
        if booking.status == BookingStatus.cancelled:
            return booking
        if booking.status == BookingStatus.completed:
            raise HTTPException(status_code=400, detail="Cannot cancel a completed booking.")

        old_status = booking.status
        was_active = booking.status == BookingStatus.active
        booking.status = BookingStatus.cancelled
        booking.cancellation_reason = reason.value
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancelled_by = None

        if was_active:
            vehicle = await cls._load_vehicle_locked(db, booking.vehicle_id, booking.tenant_id)
            vehicle.status = VehicleStatus.available
            vehicle.mileage_due = True

            # ✅ Log vehicle return on client cancel (safe client read)
            try:
                await VehicleActivityLogger.on_returned(
                    db=db,
                    tenant_id=booking.tenant_id,
                    user_id=None,
                    vehicle=vehicle,
                    booking_number=booking.booking_number,
                    client_name=_client_name(booking),
                )
            except Exception as e:
                print(f"⚠️ Warning: Failed to log vehicle return on client cancel: {e}")

        # ✅ NEW: Log the booking status change
        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=booking.tenant_id,
                user_id=None,
                booking=booking,
                old_status=old_status,
                new_status="cancelled",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log client booking cancel: {e}")

        await db.flush()
        return booking

    @classmethod
    async def start_trip_auto(cls, db: AsyncSession, booking: Booking) -> Booking:
        """
        ✅ Signed-at-handover ⇒ auto-start. FLUSH only — caller commits.
        No authenticated user (public sign) → commission created_by=None.
        Raises if preconditions fail — caller falls back to manual Start Trip.
        """
        if booking.status == BookingStatus.active:
            return booking
        if booking.status not in (BookingStatus.pending, BookingStatus.confirmed):
            raise HTTPException(status_code=400, detail="Booking cannot start.")

        client = (await db.execute(
            select(Client).where(Client.id == booking.client_id)
        )).scalars().first()
        if not client or client.status != ClientStatus.active:
            raise HTTPException(status_code=400, detail="Client must be active.")

        vehicle = await cls._load_vehicle_locked(db, booking.vehicle_id, booking.tenant_id)
        if vehicle.status != VehicleStatus.available:
            raise HTTPException(status_code=409, detail="Vehicle is not available.")

        old_status = booking.status
        booking.status = BookingStatus.active
        vehicle.status = VehicleStatus.rented

        # ✅ Commission (trial-exempt); system-triggered → created_by=None
        await cls._create_commission_event(db, booking, booking.tenant_id, None)

        # ✅ Log the vehicle rental (system-triggered, safe client read)
        try:
            await VehicleActivityLogger.on_rented(
                db=db,
                tenant_id=booking.tenant_id,
                user_id=None,
                vehicle=vehicle,
                booking_number=booking.booking_number,
                client_name=_client_name(booking),
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log auto vehicle rented: {e}")

        # ✅ Log the booking status change
        try:
            await BookingActivityLogger.on_status_changed(
                db=db,
                tenant_id=booking.tenant_id,
                user_id=None,
                booking=booking,
                old_status=old_status,
                new_status="active",
            )
        except Exception as e:
            print(f"⚠️ Warning: Failed to log auto booking start: {e}")

        await db.flush()
        return booking
