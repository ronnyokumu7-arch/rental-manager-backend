import logging
import uuid
from datetime import datetime, timezone, timedelta

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # ✅ Added for proper type hinting
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.models.subscriptions import Subscription, SubscriptionStatus, PlanType, BillingCycle
from app.models.tenants import Tenant
from app.services.cache import invalidate_subscription_cache  # ✅ NEW: For cache invalidation
from app.services.email import (
    send_trial_ending_warning,
    send_subscription_past_due,
    send_subscription_suspended,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize async Redis client for distributed locking
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


async def run_subscription_lifecycle():
    """
    Daily subscription lifecycle check.
    Uses a Redis distributed lock to prevent duplicate execution across multiple workers/pods.
    """
    lock_name = "lock:subscription_lifecycle"
    lock_token = uuid.uuid4().hex
    lock_timeout = 3600  # 1 hour TTL (prevents deadlocks if job crashes)

    # 1. Attempt to acquire distributed lock (with graceful failure if Redis is down)
    try:
        acquired = await redis_client.set(lock_name, lock_token, nx=True, ex=lock_timeout)
    except Exception as e:
        logger.error(f"Failed to connect to Redis for distributed lock: {e}")
        return

    if not acquired:
        logger.info("Subscription lifecycle job is already running on another instance. Skipping.")
        return

    logger.info("Running subscription lifecycle job...")
    
    # 2. Use async context manager for safe session lifecycle
    try:
        async with AsyncSessionLocal() as db:
            try:
                now = datetime.now(timezone.utc)

                # 3. Await all async helper functions
                await _handle_trial_ending_warnings(db, now)
                await _handle_trial_conversions(db, now)
                await _handle_expired_subscriptions(db, now)
                await _handle_grace_period_expirations(db, now)

                # 4. Commit all changes in a single transaction
                await db.commit()
                logger.info("Subscription lifecycle job DB updates completed successfully.")
            except Exception as e:
                await db.rollback()
                logger.error(f"Subscription lifecycle job failed and rolled back: {e}", exc_info=True)
    finally:
        # Do not delete a lock acquired by a later job after this one expires.
        try:
            if await redis_client.get(lock_name) == lock_token:
                await redis_client.delete(lock_name)
        except Exception:
            logger.warning("Could not release subscription lifecycle lock", exc_info=True)


async def _handle_trial_conversions(db: AsyncSession, now: datetime):
    """Convert free_trial → starter_trial when trial ends."""
    stmt = select(Subscription).options(selectinload(Subscription.tenant)).where(
        Subscription.plan == PlanType.free_trial,
        Subscription.status == SubscriptionStatus.trial,
        Subscription.ends_at <= now,
    )
    result = await db.execute(stmt)
    expired_trials = result.scalars().all()

    for sub in expired_trials:
        logger.info(f"Converting tenant {sub.tenant_id} from free_trial to starter_trial")
        new_ends_at = now + timedelta(days=14)
        new_grace = new_ends_at + timedelta(days=7)

        sub.plan = PlanType.starter_trial
        sub.status = SubscriptionStatus.starter_trial
        sub.starts_at = now
        sub.ends_at = new_ends_at
        sub.grace_period_ends_at = new_grace

        tenant = sub.tenant
        if tenant:
            tenant.plan = PlanType.starter_trial.value
            tenant.subscription_status = SubscriptionStatus.starter_trial
            tenant.trial_ends_at = new_ends_at
            tenant.subscription_ends_at = new_ends_at
            tenant.grace_period_ends_at = new_grace
            
            # ✅ Invalidate cache so warnings update immediately
            await invalidate_subscription_cache(tenant.id)


async def _handle_expired_subscriptions(db: AsyncSession, now: datetime):
    """Move active/starter_trial subscriptions to past_due when they expire."""
    stmt = select(Subscription).options(selectinload(Subscription.tenant)).where(
        Subscription.status.in_([
            SubscriptionStatus.active,
            SubscriptionStatus.starter_trial,
        ]),
        Subscription.ends_at <= now,
    )
    result = await db.execute(stmt)
    expired = result.scalars().all()

    for sub in expired:
        logger.info(f"Moving tenant {sub.tenant_id} subscription to past_due")
        sub.status = SubscriptionStatus.past_due

        tenant = sub.tenant
        if tenant:
            tenant.subscription_status = SubscriptionStatus.past_due
            
            # ✅ Invalidate cache
            await invalidate_subscription_cache(tenant.id)
            
            # ✅ Wrap email in try/except so a failure doesn't rollback the DB transaction
            try:
                # NOTE: If send_subscription_past_due is async in your codebase, add 'await' here.
                await send_subscription_past_due(
                    to=tenant.email,
                    company_name=tenant.name,
                    grace_period_ends_at=sub.grace_period_ends_at.strftime("%d %b %Y") if sub.grace_period_ends_at else "—",
                )
            except Exception as e:
                logger.error(f"Failed to send past due email to {tenant.email}: {e}")


async def _handle_grace_period_expirations(db: AsyncSession, now: datetime):
    """Suspend tenants whose grace period has ended."""
    stmt = select(Subscription).options(selectinload(Subscription.tenant)).where(
        Subscription.status == SubscriptionStatus.past_due,
        Subscription.grace_period_ends_at <= now,
    )
    result = await db.execute(stmt)
    grace_expired = result.scalars().all()

    for sub in grace_expired:
        logger.info(f"Suspending tenant {sub.tenant_id} — grace period expired")
        sub.status = SubscriptionStatus.suspended

        tenant = sub.tenant
        if tenant:
            tenant.subscription_status = SubscriptionStatus.suspended
            
            # ✅ Invalidate cache
            await invalidate_subscription_cache(tenant.id)
            
            # ✅ Wrap email in try/except
            try:
                await send_subscription_suspended(
                    to=tenant.email,
                    company_name=tenant.name,
                )
            except Exception as e:
                logger.error(f"Failed to send suspended email to {tenant.email}: {e}")


async def _handle_trial_ending_warnings(db: AsyncSession, now: datetime):
    """Warn tenants whose trial ends in 7 days or fewer."""
    warning_threshold = now + timedelta(days=7)

    stmt = select(Subscription).options(selectinload(Subscription.tenant)).where(
        Subscription.status.in_([
            SubscriptionStatus.trial,
            SubscriptionStatus.starter_trial,
        ]),
        Subscription.ends_at <= warning_threshold,
        Subscription.ends_at > now,
    )
    result = await db.execute(stmt)
    upcoming = result.scalars().all()

    for sub in upcoming:
        tenant = sub.tenant
        if tenant and sub.ends_at:
            delta = sub.ends_at - now
            days_left = max(0, delta.days)
            
            # ✅ Wrap email in try/except
            try:
                await send_trial_ending_warning(
                    to=tenant.email,
                    company_name=tenant.name,
                    days_left=days_left,
                    trial_ends_at=sub.ends_at.strftime("%d %b %Y"),
                )
            except Exception as e:
                logger.error(f"Failed to send trial ending warning to {tenant.email}: {e}")
