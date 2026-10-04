# app/routers/reports.py
"""
Reporting Endpoints — revenue, bookings, utilisation, and platform health.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B): Heavy PDF/Excel generation is now wrapped in try/except
   to catch crashes (e.g., OOM, missing fonts) and return a clean ServerError
   instead of a raw 500 stack trace.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ServerError
from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.services.reports import (
    build_excel_report,
    build_overdue_pdf,
    build_revenue_pdf,
    build_vehicle_utilisation_pdf,
    get_booking_summary,
    get_client_activity,
    get_overdue_bookings,
    get_platform_revenue,
    get_revenue_summary,
    get_subscription_health,
    get_vehicle_utilisation,
)

router = APIRouter(prefix="/reports", tags=["reports"])

# The Bouncers
admin_only = Depends(require_role([UserRole.super_admin, UserRole.tenant_admin]))
super_admin_only = Depends(require_role([UserRole.super_admin]))


# ---------------------------------------------------------------------------
# Business Logic Helpers
# ---------------------------------------------------------------------------

async def _get_tenant_name(tenant_id: Optional[int], db: AsyncSession) -> str:
    """Async helper to fetch tenant name."""
    if not tenant_id:
        return "All Tenants"
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalars().first()
    return tenant.name if tenant else "Unknown"


def _get_report_tenant_id(user: User) -> Optional[int]:
    """Centralized helper to resolve tenant context."""
    return None if user.role == UserRole.super_admin else user.tenant_id


# ---------------------------------------------------------------------------
# Revenue report
# ---------------------------------------------------------------------------

@router.get("/revenue")
@limiter.limit("10/minute")  # 🚨 Heavy operation (PDF/Excel generation)
async def revenue_report(
    request: Request,
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_only,
):
    tenant_id = _get_report_tenant_id(current_user)
    
    # ⚠️ NOTE: Ensure get_revenue_summary inside app.services.reports is updated to async 
    # and accepts AsyncSession, otherwise it will block the event loop.
    data = get_revenue_summary(db, tenant_id, start_date, end_date)

    if format == "json":
        return data

    tenant_name = await _get_tenant_name(tenant_id, db)

    try:
        if format == "pdf":
            pdf = build_revenue_pdf(data, tenant_name)
            return Response(
                content=pdf,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=revenue-report.pdf"},
            )

        excel = build_excel_report("revenue", data, tenant_name)
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=revenue-report.xlsx"},
        )
    except Exception as e:
        print(f"⚠️ Revenue report generation failed: {e}")
        raise ServerError(
            title="Report Generation Failed",
            message="We couldn't generate this report right now. Please try again or contact support.",
        )


# ---------------------------------------------------------------------------
# Booking summary
# ---------------------------------------------------------------------------

@router.get("/bookings")
@limiter.limit("10/minute")
async def booking_summary_report(
    request: Request,
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_only,
):
    tenant_id = _get_report_tenant_id(current_user)
    data = get_booking_summary(db, tenant_id, start_date, end_date)

    if format == "json":
        return data

    if format == "excel":
        tenant_name = await _get_tenant_name(tenant_id, db)
        try:
            excel = build_excel_report("booking_summary", data, tenant_name)
            return Response(
                content=excel,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=booking-summary.xlsx"},
            )
        except Exception as e:
            print(f"⚠️ Booking summary report generation failed: {e}")
            raise ServerError(
                title="Report Generation Failed",
                message="We couldn't generate this report right now. Please try again or contact support.",
            )

    raise BadRequestError(
        title="Format Unavailable",
        message="PDF format is not available for booking summary reports. Please use excel or json.",
    )


# ---------------------------------------------------------------------------
# Vehicle utilisation
# ---------------------------------------------------------------------------

@router.get("/vehicle-utilisation")
@limiter.limit("10/minute")
async def vehicle_utilisation_report(
    request: Request,
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise BadRequestError(
            title="Cross-Tenant Data",
            message="Please use the platform revenue report for cross-tenant data.",
        )
        
    tenant_id = current_user.tenant_id
    data = get_vehicle_utilisation(db, tenant_id, start_date, end_date)
    tenant_name = await _get_tenant_name(tenant_id, db)

    if format == "json":
        return data
        
    try:
        if format == "pdf":
            pdf = build_vehicle_utilisation_pdf(data, tenant_name)
            return Response(
                content=pdf,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=vehicle-utilisation.pdf"},
            )

        excel = build_excel_report("vehicle_utilisation", data, tenant_name)
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=vehicle-utilisation.xlsx"},
        )
    except Exception as e:
        print(f"⚠️ Vehicle utilisation report generation failed: {e}")
        raise ServerError(
            title="Report Generation Failed",
            message="We couldn't generate this report right now. Please try again or contact support.",
        )


# ---------------------------------------------------------------------------
# Client activity
# ---------------------------------------------------------------------------

@router.get("/client-activity")
@limiter.limit("10/minute")
async def client_activity_report(
    request: Request,
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise BadRequestError(
            title="Tenant-Specific Report",
            message="Client activity is tenant-specific. Please log in as a tenant admin.",
        )
    
    tenant_id = current_user.tenant_id
    data = get_client_activity(db, tenant_id, start_date, end_date)
    tenant_name = await _get_tenant_name(tenant_id, db)

    if format == "json":
        return data

    try:
        excel = build_excel_report("client_activity", data, tenant_name)
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=client-activity.xlsx"},
        )
    except Exception as e:
        print(f"⚠️ Client activity report generation failed: {e}")
        raise ServerError(
            title="Report Generation Failed",
            message="We couldn't generate this report right now. Please try again or contact support.",
        )


# ---------------------------------------------------------------------------
# Overdue bookings
# ---------------------------------------------------------------------------

@router.get("/overdue")
@limiter.limit("10/minute")
async def overdue_report(
    request: Request,
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise BadRequestError(
            title="Tenant-Specific Report",
            message="Overdue report is tenant-specific. Please log in as a tenant admin.",
        )
        
    tenant_id = current_user.tenant_id
    data = get_overdue_bookings(db, tenant_id)
    tenant_name = await _get_tenant_name(tenant_id, db)

    if format == "json":
        return data
        
    try:
        if format == "pdf":
            pdf = build_overdue_pdf(data, tenant_name)
            return Response(
                content=pdf,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=overdue-bookings.pdf"},
            )

        excel = build_excel_report("overdue", data, tenant_name)
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=overdue-bookings.xlsx"},
        )
    except Exception as e:
        print(f"⚠️ Overdue report generation failed: {e}")
        raise ServerError(
            title="Report Generation Failed",
            message="We couldn't generate this report right now. Please try again or contact support.",
        )


# ---------------------------------------------------------------------------
# Platform reports (super_admin only)
# ---------------------------------------------------------------------------

@router.get("/platform-revenue")
@limiter.limit("10/minute")
async def platform_revenue_report(
    request: Request,
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    data = get_platform_revenue(db)

    if format == "json":
        return data

    try:
        excel = build_excel_report("platform_revenue", data, "All Tenants")
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=platform-revenue.xlsx"},
        )
    except Exception as e:
        print(f"⚠️ Platform revenue report generation failed: {e}")
        raise ServerError(
            title="Report Generation Failed",
            message="We couldn't generate this report right now. Please try again or contact support.",
        )


@router.get("/subscription-health")
@limiter.limit("30/minute")
async def subscription_health_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = super_admin_only,
):
    return get_subscription_health(db)
