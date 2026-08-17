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
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.platform_settings import PlatformSettings
from app.models.tenants import Tenant

logger = logging.getLogger(__name__)

PLATFORM_TZ = ZoneInfo("Africa/Nairobi")


# ---------------------------------------------------------------------------
# EMAIL ADAPTER — adjust the import path/signature if your email utility differs
# ---------------------------------------------------------------------------
async def _send_email(to: str, subject: str, html: str) -> bool:
    """
    Reuses the same email utility your password-reset flow uses.
    TODO: Confirm the import path matches your actual email service.
    """
    try:
        from app.services.email import send_email  # ← confirm this path/signature
        await send_email(to=to, subject=subject, html_content=html)
        return True
    except Exception as exc:
        logger.error(f"[daily_commission] email failed to {to}: {exc}")
        return False


def _statement_html(
    tenant_name: str,
    trip_count: int,
    total: Decimal,
    days_until_lock: int,
    paybill: Optional[str],
    account_number: Optional[str],
    account_name: Optional[str],
) -> str:
    if days_until_lock == 0:
        headline, color = "Account soft-locked", "#e11d48"
    elif days_until_lock <= 2:
        headline, color = f"{days_until_lock} day(s) until soft-lock", "#d97706"
    else:
        headline, color = "Daily commission statement", "#2563eb"

    pay_url = os.getenv("FRONTEND_URL", "")
    pay_link = (
        f'<p style="margin:16px 0"><a href="{pay_url}/commission/pay" '
        f'style="background:#2563eb;color:#fff;padding:10px 18px;border-radius:8px;'
        f'text-decoration:none;font-weight:bold">Pay Commission</a></p>'
        if pay_url
        else "<p>Log in and visit <b>Commission → Pay</b> to settle.</p>"
    )

    paybill_block = (
        f"<p>PayBill: <b>{paybill}</b><br>Account No: <b>{account_number}</b><br>"
        f"Account Name: <b>{account_name}</b></p>"
        if paybill and account_number
        else "<p>Payment details are in your dashboard under Commission → Pay.</p>"
    )

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:24px">
      <h2 style="color:{color}">{headline}</h2>
      <p>Hi {tenant_name},</p>
      <p>You have <b>{trip_count}</b> unpaid trip(s) totalling <b>KES {total:,.2f}</b>.</p>
      {paybill_block}
      {pay_link}
      <p style="color:#6b7280;font-size:12px">Royride Platform • Commission Office</p>
    </div>
    """


# ---------------------------------------------------------------------------
# THE ROUTINE (called by APScheduler + manual trigger)
# ---------------------------------------------------------------------------
async def run_daily_commission_routine(db: Optional[AsyncSession] = None) -> dict:
    """
    Email statements with escalating severity.
    If db is None, creates its own session (scheduler context).
    If db is provided, uses it (manual trigger context).
    """
    now = datetime.now(PLATFORM_TZ)

    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await _run_routine_logic(session, now)
    else:
        return await _run_routine_logic(db, now)


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

    stats = {"statements": 0, "warnings": 0, "lock_notices": 0, "skipped": 0}

    for tenant_id, count, total, oldest_at in rows:
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
        html = _statement_html(
            tenant_name=tenant.name,
            trip_count=int(count),
            total=total_dec,
            days_until_lock=days_until_lock,
            paybill=settings.platform_paybill if settings else None,
            account_number=settings.platform_account_number if settings else None,
            account_name=settings.platform_account_name if settings else None,
        )

        if days_until_lock == 0:
            subject = f"🔒 {tenant.name}: account soft-locked — settle KES {total_dec:,.0f} to unlock"
            ok = await _send_email(to_email, subject, html)
            stats["lock_notices"] += 1 if ok else 0
        elif days_until_lock <= 2:
            subject = f"⚠️ {days_until_lock} day(s) left: KES {total_dec:,.0f} commission due"
            ok = await _send_email(to_email, subject, html)
            stats["warnings"] += 1 if ok else 0
        else:
            subject = f"{tenant.name}: daily commission statement — KES {total_dec:,.0f} outstanding"
            ok = await _send_email(to_email, subject, html)
            stats["statements"] += 1 if ok else 0

    return stats
