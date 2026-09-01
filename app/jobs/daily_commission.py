# app/jobs/daily_commission.py
"""
✅ DAILY COMMISSION ROUTINE (00:05H EAT / 21:05H UTC)

Emails tenants their commission statement with escalating severity:
- days_until_lock > 2: 📄 Daily statement
- days_until_lock 1–2: ⚠️ Warning
- days_until_lock == 0: 🔒 Lock notice (sent once)
- days_until_lock < 0: Silent (already locked — no spam)

Stateless: severity derived from oldest unpaid age (no extra tables).
"""
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis
from app.services.email import send_commission_statement
from app.db.database import AsyncSessionLocal
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.platform_settings import PlatformSettings
from app.models.tenants import Tenant

logger = logging.getLogger(__name__)

PLATFORM_TZ = ZoneInfo("Africa/Nairobi")

EMPTY_STATS = {"statements": 0, "warnings": 0, "lock_notices": 0, "skipped": 0, "errors": 0}


# ---------------------------------------------------------------------------
# THE ROUTINE (called by APScheduler + manual trigger)
# ---------------------------------------------------------------------------
async def run_daily_commission_routine(db: Optional[AsyncSession] = None) -> dict:
    """
    Email statements with escalating severity.
    If db is None, creates its own session (scheduler context).
    If db is provided, uses it (manual trigger context).

    ✅ Distributed lock (fail-soft) applies ONLY in scheduler context, so a
    manual trigger is never blocked by Redis being down or a scheduled run.
    """
    now = datetime.now(PLATFORM_TZ)

    redis_client = None
    lock_token = uuid.uuid4().hex
    lock_name = "lock:daily_commission"
    lock_timeout = 3600

    if db is None:
        redis_client = await get_redis()
        if redis_client is None:
            logger.warning(
                "⚠️ Redis unavailable — skipping scheduled commission routine to "
                "prevent duplicate emails. Job retries on next execution."
            )
            return dict(EMPTY_STATS)

        try:
            acquired = await redis_client.set(lock_name, lock_token, nx=True, ex=lock_timeout)
        except Exception as exc:
            logger.error("Failed to acquire daily commission lock: %s", exc)
            return dict(EMPTY_STATS)

        if not acquired:
            logger.info("Daily commission routine already running on another instance. Skipping.")
            return dict(EMPTY_STATS)

    try:
        if db is None:
            async with AsyncSessionLocal() as session:
                return await _run_routine_logic(session, now)
        else:
            return await _run_routine_logic(db, now)
    finally:
        # ✅ Release the lock only if we still own it
        if redis_client is not None:
            try:
                current_token = await redis_client.get(lock_name)
                if current_token == lock_token:
                    await redis_client.delete(lock_name)
                    logger.debug("Daily commission lock released.")
                else:
                    logger.warning("Lock token mismatch on release — lock may have expired or been stolen.")
            except Exception:
                logger.warning("Could not release daily commission lock", exc_info=True)


async def _run_routine_logic(db: AsyncSession, now: datetime) -> dict:
    """Core logic separated for session flexibility."""
    settings = (
        await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    ).scalars().first()
    grace_days = settings.grace_period_days if settings else 3

    # Per-tenant unpaid picture (oldest event first-day)
    stmt = (
        select(
            CommissionEvent.tenant_id,
            func.count(CommissionEvent.id),
            func.coalesce(func.sum(CommissionEvent.amount), 0),
            func.min(CommissionEvent.trip_started_at),
        )
        .where(CommissionEvent.status == CommissionStatus.unpaid)
        .group_by(CommissionEvent.tenant_id)
    )
    rows = (await db.execute(stmt)).all()

    stats = dict(EMPTY_STATS)

    for tenant_id, count, total, oldest_at in rows:
        # ✅ Per-tenant isolation: one bad row must not kill the whole run
        try:
            if oldest_at is None:
                stats["skipped"] += 1
                logger.warning(f"[daily_commission] tenant {tenant_id}: oldest trip date is NULL — skipped.")
                continue

            age_days = (now.date() - oldest_at.astimezone(PLATFORM_TZ).date()).days
            if age_days < 1:
                stats["skipped"] += 1
                continue  # only previous-day debt gets emailed

            days_until_lock = grace_days - age_days
            if days_until_lock < 0:
                stats["skipped"] += 1
                continue  # already locked — no spam

            tenant = await db.get(Tenant, tenant_id)
            if not tenant:
                stats["skipped"] += 1
                continue
            to_email = getattr(tenant, "admin_email", None) or tenant.email
            if not to_email:
                stats["skipped"] += 1
                continue

            total_dec = Decimal(total)
            
            # ✅ Send via the dedicated commission email service
            ok = await send_commission_statement(
                to=to_email,
                tenant_name=tenant.name,
                trip_count=int(count),
                total=total_dec,
                days_until_lock=days_until_lock,
                paybill=settings.platform_paybill if settings else None,
                account_number=settings.platform_account_number if settings else None,
                account_name=settings.platform_account_name if settings else None,
            )

            # Track stats by severity
            if days_until_lock == 0:
                stats["lock_notices"] += 1 if ok else 0
            elif days_until_lock <= 2:
                stats["warnings"] += 1 if ok else 0
            else:
                stats["statements"] += 1 if ok else 0

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"[daily_commission] tenant {tenant_id} failed: {e}", exc_info=True)
            continue

    logger.info(f"[daily_commission] run complete: {stats}")
    return stats
