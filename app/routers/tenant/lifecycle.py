# app/routers/tenant/lifecycle.py
"""
✅ TENANT LIFECYCLE — single owner of suspend / unsuspend / vault / restore / billing-mode switch.

CONTRACT RULES:
  - Lifecycle transitions NEVER flow through the generic TenantUpdate endpoint.
  - Suspend & Vault require a typed reason payload (audited).
  - A super-admin can NEVER suspend or vault their OWN tenant (lockout guard).
  - Unsuspend & Restore ARE allowed on own tenant (recovery path while session lives).
  - suspended_at / vaulted_at timestamps are ALWAYS written — they are the
    audit truth and the source for effective_status derivation.
  - ✅ PAYG TRANSITION is self-service (tenant owner OR super-admin) and DEBT-GATED:
    any unpaid platform commission must be settled FIRST. NO automatic waivers —
    waiver remains a manual super-admin correction tool, never a side effect.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.commission import CommissionEvent, CommissionStatus
from app.models.subscriptions import BillingCycle, PlanType, Subscription, SubscriptionStatus
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.schemas.tenant import (
    TenantOut,
    TenantSuspendPayload,
    TenantUnsuspendPayload,
    TenantVaultPayload,
    TenantRestorePayload,
)
from app.services.cache import invalidate_subscription_cache, invalidate_tenant_cache
from app.services.activity_log import TenantActivityLogger

router = APIRouter()

super_admin_only = Depends(require_role([UserRole.super_admin]))


async def _load_tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    stmt = select(Tenant).options(selectinload(Tenant.profile)).where(Tenant.id == tenant_id)
    tenant = (await db.execute(stmt)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _guard_self(current_user: User, tenant_id: int, action: str) -> None:
    """✅ LOCKOUT GUARD: never suspend/vault/delete your own agency."""
    if current_user.tenant_id == tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You cannot {action} your own agency account. Ask another super-admin to perform this action.",
        )


@router.post("/{tenant_id}/suspend", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Locks an entire agency out
async def suspend_tenant(
    request: Request,
    tenant_id: int,
    payload: TenantSuspendPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    _guard_self(current_user, tenant_id, "suspend")
    tenant = await _load_tenant(db, tenant_id)

    if tenant.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vaulted tenants cannot be suspended. Restore from the Vault first if needed.",
        )
    if not tenant.is_active:
        return tenant  # idempotent

    tenant.is_active = False
    tenant.suspended_at = datetime.now(timezone.utc)   # ✅ FIX: timestamp was never written
    tenant.suspension_reason = payload.reason
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    await invalidate_tenant_cache()
    await TenantActivityLogger.on_suspended(db, current_user.id, tenant, payload.reason)
    await db.commit()  # Commit the activity log flush

    return tenant


@router.post("/{tenant_id}/activate", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Restores agency access
async def activate_tenant(
    request: Request,
    tenant_id: int,
    payload: Optional[TenantUnsuspendPayload] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    tenant = await _load_tenant(db, tenant_id)

    if tenant.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vaulted tenants cannot be activated. Use Restore from the Vault instead.",
        )
    if tenant.is_active and tenant.suspended_at is None:
        return tenant  # idempotent

    tenant.is_active = True
    tenant.suspended_at = None          # ✅ FIX: clear the suspension timestamp
    tenant.suspension_reason = None
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    await invalidate_tenant_cache()
    await TenantActivityLogger.on_activated(db, current_user.id, tenant)
    await db.commit()

    return tenant


@router.post("/{tenant_id}/archive", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Moves tenant to vault
async def archive_tenant(
    request: Request,
    tenant_id: int,
    payload: TenantVaultPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """Moves tenant to Vault (soft delete) with a recorded reason."""
    _guard_self(current_user, tenant_id, "vault")
    tenant = await _load_tenant(db, tenant_id)

    if tenant.is_archived:
        return tenant  # idempotent

    tenant.is_archived = True
    tenant.is_active = False
    tenant.vaulted_at = datetime.now(timezone.utc)   # ✅ Vault audit trail
    tenant.vault_reason = payload.reason
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    await invalidate_tenant_cache()
    await TenantActivityLogger.on_archived(db, current_user.id, tenant)
    await db.commit()

    return tenant


@router.post("/{tenant_id}/restore", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 STRICT: Brings tenant back from vault
async def restore_tenant(
    request: Request,
    tenant_id: int,
    payload: Optional[TenantRestorePayload] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    """
    ✅ RESTORE FROM VAULT — the missing recovery path.
    Returns the agency to active operation; suspension state is cleared
    (re-suspend explicitly afterwards if still warranted).
    Allowed on own tenant: this is the recovery path while a session lives.
    """
    tenant = await _load_tenant(db, tenant_id)

    if not tenant.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This tenant is not in the Vault.",
        )

    tenant.is_archived = False
    tenant.is_active = True
    tenant.suspended_at = None
    tenant.suspension_reason = None
    tenant.vaulted_at = None
    tenant.vault_reason = None
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    await invalidate_tenant_cache()
    on_restored = getattr(TenantActivityLogger, "on_restored", None)
    if on_restored:
        await on_restored(db, current_user.id, tenant)
    else:
        await TenantActivityLogger.on_activated(db, current_user.id, tenant)
    await db.commit()

    return tenant


@router.post("/{tenant_id}/transition-to-payg", response_model=TenantOut)
@limiter.limit("10/minute")  # 🚨 Billing-mode change
async def transition_to_payg(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ SELF-SERVICE PAYG SWITCH — tenant admin (own tenant) or super-admin (any).
    CONTRACT RULES:
      - NO automatic waivers: any unpaid platform commission must be settled
        FIRST (409 otherwise). Waiver stays a manual super-admin correction tool.
      - Idempotent: already-PAYG tenants return unchanged.
      - Vaulted / suspended tenants cannot switch billing mode.
      - Clears trial/subscription dates: PAYG has no renewal cycle.
      - Keeps the subscriptions ledger consistent (latest row flips to PAYG).
    """
    if current_user.role != UserRole.super_admin and current_user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only change your own agency's billing mode.",
        )
    tenant = await _load_tenant(db, tenant_id)

    if tenant.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vaulted tenants cannot change billing mode. Restore from the Vault first.",
        )
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suspended tenants cannot change billing mode. Activate first.",
        )

    if tenant.billing_cycle == "pay_as_you_go":
        return tenant  # idempotent

    # ✅ DEBT GATE: they owe the system → settle first. No silent forgiveness.
    owed = (
        await db.execute(
            select(func.coalesce(func.sum(CommissionEvent.amount), 0)).where(
                CommissionEvent.tenant_id == tenant_id,
                CommissionEvent.status == CommissionStatus.unpaid,
            )
        )
    ).scalar() or 0
    if Decimal(owed) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Outstanding platform commission of KES {Decimal(owed):,} must be "
                "settled before changing plan. Settle it via Commission → Pay, or "
                "contact support."
            ),
        )

    now = datetime.now(timezone.utc)
    tenant.plan = "pay_as_you_go"
    tenant.billing_cycle = "pay_as_you_go"
    tenant.subscription_status = SubscriptionStatus.active
    tenant.trial_ends_at = None
    tenant.subscription_ends_at = None
    tenant.grace_period_ends_at = None

    # ✅ Keep the subscription ledger consistent (latest row flips to PAYG, no expiry)
    sub = (
        await db.execute(
            select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().first()
    if sub:
        sub.plan = PlanType.pay_as_you_go
        sub.billing_cycle = BillingCycle.pay_as_you_go
        sub.status = SubscriptionStatus.active
        sub.starts_at = now
        sub.ends_at = None
        sub.grace_period_ends_at = None
        sub.auto_renew = False
    else:
        db.add(Subscription(
            tenant_id=tenant_id,
            plan=PlanType.pay_as_you_go,
            billing_cycle=BillingCycle.pay_as_you_go,
            status=SubscriptionStatus.active,
            starts_at=now,
            ends_at=None,
            auto_renew=False,
        ))

    await db.commit()
    await db.refresh(tenant)
    await db.refresh(tenant.profile)

    await invalidate_tenant_cache()
    await invalidate_subscription_cache(tenant_id)
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")  # 🚨 EXTREMELY STRICT: Destructive action
async def delete_tenant(
    request: Request,
    tenant_id: int,
    hard_delete: bool = Query(False, description="Permanently remove from DB instead of archiving"),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    _guard_self(current_user, tenant_id, "delete")
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # ✅ Capture tenant details BEFORE deletion (object becomes detached after db.delete)
    tenant_name = tenant.name
    tenant_id_for_log = tenant.id

    if hard_delete:
        await db.delete(tenant)
        await db.commit()
    else:
        # Default behavior is soft delete / archive
        tenant.is_archived = True
        tenant.is_active = False
        tenant.vaulted_at = datetime.now(timezone.utc)
        tenant.vault_reason = "Deleted by super-admin"
        await db.commit()

    await invalidate_tenant_cache()
    await TenantActivityLogger.on_deleted(
        db, current_user.id, tenant_id_for_log, tenant_name, hard_delete
    )
    await db.commit()  # Commit the activity log flush
