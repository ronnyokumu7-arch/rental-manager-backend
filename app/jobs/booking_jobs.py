import logging
import uuid
from datetime import datetime, timezone, timedelta

import redis.asyncio as redis
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.models.bookings import Booking, BookingStatus

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize async Redis client for distributed locking
redis_client = redis.from_url(settings.redis_url, decode_responses=True)

ARCHIVE_AFTER_DAYS = 30


async def run_booking_auto_archive():
    """
    Auto-archives old bookings. 
    Uses a Redis distributed lock to prevent duplicate execution across multiple workers/pods.
    """
    lock_name = "lock:booking_auto_archive"
    lock_token = uuid.uuid4().hex
    lock_timeout = 3600  # 1 hour TTL (prevents deadlocks if job crashes)

    # 1. Attempt to acquire distributed lock
    # nx=True means "set only if it does not exist"
    try:
        acquired = await redis_client.set(lock_name, lock_token, nx=True, ex=lock_timeout)
    except Exception as exc:
        logger.error("Failed to acquire booking archive lock: %s", exc)
        return
    
    if not acquired:
        logger.info("Booking auto-archive job is already running on another instance. Skipping.")
        return

    logger.info("Starting booking auto-archive job...")
    
    # 2. Use async context manager for safe session lifecycle (auto-closes)
    count = 0
    try:
        async with AsyncSessionLocal() as db:
            try:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(days=ARCHIVE_AFTER_DAYS)

                archivable_statuses = [
                    BookingStatus.completed,
                    BookingStatus.cancelled,
                    BookingStatus.no_show,
                ]

                # 3. Fetch records using async SQLAlchemy (select + execute)
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

                # 4. Process records in memory
                for booking in bookings:
                    booking.is_archived = True
                    booking.archived_at = now
                    count += 1

                # 5. Commit all changes in a single transaction
                await db.commit()
                logger.info(f"Successfully auto-archived {count} bookings.")

            except Exception as e:
                # Explicit rollback on failure
                await db.rollback()
                logger.error(f"Booking auto-archive job failed: {e}", exc_info=True)
            
    finally:
        try:
            if await redis_client.get(lock_name) == lock_token:
                await redis_client.delete(lock_name)
        except Exception:
            logger.warning("Could not release booking archive lock", exc_info=True)
