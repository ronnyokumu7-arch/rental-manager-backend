# app/jobs/booking_jobs.py
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.redis_client import get_redis
from app.db.database import AsyncSessionLocal
from app.models.bookings import Booking, BookingStatus
from app.services.booking_lifecycle import BookingLifecycleService

logger = logging.getLogger(__name__)

ARCHIVE_AFTER_DAYS = 30
AUTO_END_GRACE_HOURS = 2  # ✅ Operator buffer to extend / follow up before auto-end


async def run_booking_auto_archive():
    """
    Auto-archives old bookings (completed or cancelled, including no-shows).
    Uses a Redis distributed lock to prevent duplicate execution across multiple workers/pods.
    Fail-soft: if Redis is unavailable, the job skips with a warning (does not crash).

    ✅ No-show bookings are archived automatically — they have status=cancelled
    with cancellation_reason="no_show", so they're captured by the cancelled filter.
    """
    redis_client = await get_redis()
    if redis_client is None:
        logger.warning(
            "⚠️ Redis unavailable — skipping booking auto-archive to prevent duplicate runs. "
            "Job will retry on next scheduled execution."
        )
        return

    lock_name = "lock:booking_auto_archive"
    lock_token = uuid.uuid4().hex
    lock_timeout = 3600

    try:
        acquired = await redis_client.set(lock_name, lock_token, nx=True, ex=lock_timeout)
    except Exception as exc:
        logger.error("Failed to acquire booking archive lock: %s", exc)
        return

    if not acquired:
        logger.info("Booking auto-archive job is already running on another instance. Skipping.")
        return

    logger.info("Starting booking auto-archive job...")

    count = 0
    try:
        async with AsyncSessionLocal() as db:
            try:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(days=ARCHIVE_AFTER_DAYS)

                # ✅ Only terminal statuses — no-shows are status=cancelled
                # with cancellation_reason="no_show", so they're included here.
                archivable_statuses = [
                    BookingStatus.completed,
                    BookingStatus.cancelled,
                ]

                stmt = select(Booking).where(
                    Booking.status.in_(archivable_statuses),
                    Booking.is_archived == False,
                    Booking.updated_at <= cutoff,
                )
                result = await db.execute(stmt)
                bookings = result.scalars().all()

                if not bookings:
                    logger.info("No bookings found to archive.")
                    return

                for booking in bookings:
                    booking.is_archived = True
                    booking.archived_at = now
                    count += 1

                await db.commit()
                logger.info(f"Successfully auto-archived {count} bookings.")

            except Exception as e:
                await db.rollback()
                logger.error(f"Booking auto-archive job failed: {e}", exc_info=True)

    finally:
        try:
            current_token = await redis_client.get(lock_name)
            if current_token == lock_token:
                await redis_client.delete(lock_name)
                logger.debug("Booking archive lock released.")
            else:
                logger.warning(
                    "Lock token mismatch on release — lock may have expired or been stolen. "
                    f"Expected: {lock_token[:8]}..., Got: {current_token[:8] if current_token else 'None'}..."
                )
        except Exception:
            logger.warning("Could not release booking archive lock", exc_info=True)


async def run_auto_end_trips():
    """
    ✅ AUTO-END TRIPS: completes active trips whose effective return instant is
    at least AUTO_END_GRACE_HOURS in the past.

    Business-rule faithful:
      - Effective return = COALESCE(scheduled_return_at, end_date) — the exact
        wall-clock instant the rental cycle ends (pickup time + N×24h).
        No 23:59 / 00:00 assumptions anywhere.
      - Extensions & reschedules shift these instants via the factory, so they
        are respected automatically (extended trips drop out of the eligible set).
      - Row-locked reload + under-lock re-check kills races vs manual complete/extend.
      - Redis distributed lock prevents duplicate runs across pods. Fail-soft.
    """
    redis_client = await get_redis()
    if redis_client is None:
        logger.warning(
            "⚠️ Redis unavailable — skipping auto-end trips to prevent duplicate runs. "
            "Job will retry on next scheduled execution."
        )
        return

    lock_name = "lock:auto_end_trips"
    lock_token = uuid.uuid4().hex
    lock_timeout = 600  # matches the scheduler interval

    try:
        acquired = await redis_client.set(lock_name, lock_token, nx=True, ex=lock_timeout)
    except Exception as exc:
        logger.error("Failed to acquire auto-end trips lock: %s", exc)
        return

    if not acquired:
        logger.info("Auto-end trips job is already running on another instance. Skipping.")
        return

    logger.info("Starting auto-end trips job (2h grace window)...")

    try:
        async with AsyncSessionLocal() as db:
            try:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=AUTO_END_GRACE_HOURS)

                # ✅ Same effective-schedule semantics as the rest of the codebase
                stmt = (
                    select(Booking)
                    .where(Booking.status == BookingStatus.active)
                    .where(
                        func.coalesce(Booking.scheduled_return_at, Booking.end_date) <= cutoff
                    )
                )
                result = await db.execute(stmt)
                candidates = result.scalars().all()

                if not candidates:
                    logger.info("No active trips past the 2-hour grace window.")
                    return

                ended_count = 0
                tenant_ids = set()

                for booking in candidates:
                    try:
                        # Row-lock reload to avoid racing a manual complete/extend
                        locked_stmt = (
                            select(Booking)
                            .options(
                                selectinload(Booking.client),
                                selectinload(Booking.vehicle),
                                selectinload(Booking.driver),
                            )
                            .where(Booking.id == booking.id)
                            .with_for_update()
                        )
                        locked = (await db.execute(locked_stmt)).scalars().unique().first()
                        if not locked or locked.status != BookingStatus.active:
                            continue

                        # Re-check under lock: an extension may have shifted the
                        # return instant since the candidate query ran.
                        effective_return = locked.scheduled_return_at or locked.end_date
                        if effective_return is None or effective_return > cutoff:
                            continue

                        await BookingLifecycleService.end_trip_auto(db, locked)
                        ended_count += 1
                        tenant_ids.add(locked.tenant_id)
                    except Exception as e:
                        # Per-booking failure must NOT kill the batch
                        logger.error(f"❌ Failed to auto-end booking {booking.id}: {e}", exc_info=True)

                if ended_count > 0:
                    await db.commit()
                    try:
                        from app.services.cache import (
                            invalidate_booking_cache,
                            invalidate_vehicle_cache,
                        )
                        for tid in tenant_ids:
                            await invalidate_booking_cache(tid)
                            await invalidate_vehicle_cache(tid)
                    except Exception as e:
                        logger.warning(f"Cache invalidation failed (non-fatal): {e}")
                    logger.info(f"✅ Auto-ended {ended_count} trip(s) past the 2-hour grace window.")
                else:
                    await db.rollback()
                    logger.info("No trips auto-ended (operators handled them first).")

            except Exception as e:
                await db.rollback()
                logger.error(f"Auto-end trips job failed: {e}", exc_info=True)

    finally:
        try:
            current_token = await redis_client.get(lock_name)
            if current_token == lock_token:
                await redis_client.delete(lock_name)
                logger.debug("Auto-end trips lock released.")
            else:
                logger.warning(
                    "Lock token mismatch on release — lock may have expired or been stolen. "
                    f"Expected: {lock_token[:8]}..., Got: {current_token[:8] if current_token else 'None'}..."
                )
        except Exception:
            logger.warning("Could not release auto-end trips lock", exc_info=True)
