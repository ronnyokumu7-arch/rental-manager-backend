# app/routers/services.py
"""
Service Catalog Export — feeds frontend selectors & future duty scheduler.

Returns the full catalog (live + parked with is_live flags) grouped by category,
each service enriched with the tenant's effective pricing config.

Single-query design: one SELECT for all tenant configs, mapped in Python.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.tenant import TenantScope, get_tenant_scope
from app.models.pricing import ServicePricingConfig
from app.models.users import User
from app.services.catalog import (
    SERVICE_CATALOG, resolve_key, to_dict,
)

router = APIRouter()


def _config_out(cfg) -> dict | None:
    if not cfg:
        return None
    return {
        "billing_model": cfg.billing_model,
        "day_hours": cfg.day_hours,
        "grace_minutes": cfg.grace_minutes,
        "overtime_hourly_rate": cfg.overtime_hourly_rate,
        "overtime_cap_at_day_rate": cfg.overtime_cap_at_day_rate,
        "driver_daily_fee": cfg.driver_daily_fee,
        "driver_overtime_hourly_fee": cfg.driver_overtime_hourly_fee,
        "driver_night_accommodation_fee": cfg.driver_night_accommodation_fee,
        "rate_extras": cfg.rate_extras or {},
    }


@router.get("/", response_model=dict)
async def list_services(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    ✅ SECURITY: tenant-scoped config lookup. Catalog itself is global (code),
    but every rate/config returned belongs strictly to the requesting tenant.
    """
    # One query for ALL tenant configs → map in Python (no N+1)
    configs = {}
    if scope.tenant_id is not None:
        stmt = select(ServicePricingConfig).where(
            ServicePricingConfig.tenant_id == scope.tenant_id,
            ServicePricingConfig.is_active.is_(True),
        )
        rows = (await db.execute(stmt)).scalars().all()
        configs = {row.service_type: row for row in rows}

    services = []
    categories: dict = {}
    for svc in SERVICE_CATALOG.values():
        cfg = configs.get(resolve_key(svc.key))
        entry = {
            **to_dict(svc),
            # Effective strategy: tenant override → catalog default
            "effective_billing_model": (
                cfg.billing_model if cfg and cfg.billing_model
                else svc.billing_model.value
            ),
            "config": _config_out(cfg),
        }
        services.append(entry)
        categories.setdefault(svc.category.value, []).append(entry)

    return {"services": services, "categories": categories}
