from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.database import get_db
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

def _get_tenant_name(tenant_id: Optional[int], db: Session) -> str:
    if not tenant_id:
        return "All Tenants"
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant.name if tenant else "Unknown"

def _get_report_tenant_id(user: User) -> Optional[int]:
    """Centralized helper to resolve tenant context."""
    return None if user.role == UserRole.super_admin else user.tenant_id


# ---------------------------------------------------------------------------
# Revenue report
# ---------------------------------------------------------------------------

@router.get("/revenue")
def revenue_report(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = admin_only,
):
    tenant_id = _get_report_tenant_id(current_user)
    data = get_revenue_summary(db, tenant_id, start_date, end_date)

    if format == "json":
        return data

    tenant_name = _get_tenant_name(tenant_id, db)

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


# ---------------------------------------------------------------------------
# Booking summary
# ---------------------------------------------------------------------------

@router.get("/bookings")
def booking_summary_report(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = admin_only,
):
    tenant_id = _get_report_tenant_id(current_user)
    data = get_booking_summary(db, tenant_id, start_date, end_date)

    if format == "json":
        return data

    if format == "excel":
        tenant_name = _get_tenant_name(tenant_id, db)
        excel = build_excel_report("booking_summary", data, tenant_name)
        return Response(
            content=excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=booking-summary.xlsx"},
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="PDF format is not available for booking summary reports. Please use excel or json.",
    )


# ---------------------------------------------------------------------------
# Vehicle utilisation
# ---------------------------------------------------------------------------

@router.get("/vehicle-utilisation")
def vehicle_utilisation_report(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please use the platform revenue report for cross-tenant data",
        )
        
    tenant_id = current_user.tenant_id
    data = get_vehicle_utilisation(db, tenant_id, start_date, end_date)
    tenant_name = _get_tenant_name(tenant_id, db)

    if format == "json":
        return data
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


# ---------------------------------------------------------------------------
# Client activity
# ---------------------------------------------------------------------------

@router.get("/client-activity")
def client_activity_report(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client activity is tenant-specific. Log in as a tenant admin.",
        )
    
    tenant_id = current_user.tenant_id
    data = get_client_activity(db, tenant_id, start_date, end_date)
    tenant_name = _get_tenant_name(tenant_id, db)

    if format == "json":
        return data

    excel = build_excel_report("client_activity", data, tenant_name)
    return Response(
        content=excel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=client-activity.xlsx"},
    )


# ---------------------------------------------------------------------------
# Overdue bookings
# ---------------------------------------------------------------------------

@router.get("/overdue")
def overdue_report(
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = admin_only,
):
    if current_user.role == UserRole.super_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Overdue report is tenant-specific. Log in as a tenant admin.",
        )
        
    tenant_id = current_user.tenant_id
    data = get_overdue_bookings(db, tenant_id)
    tenant_name = _get_tenant_name(tenant_id, db)

    if format == "json":
        return data
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


# ---------------------------------------------------------------------------
# Platform reports (super_admin only)
# ---------------------------------------------------------------------------

@router.get("/platform-revenue")
def platform_revenue_report(
    format: str = Query(default="json", pattern="^(json|pdf|excel)$"),
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    data = get_platform_revenue(db)

    if format == "json":
        return data

    excel = build_excel_report("platform_revenue", data, "All Tenants")
    return Response(
        content=excel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=platform-revenue.xlsx"},
    )


@router.get("/subscription-health")
def subscription_health_report(
    db: Session = Depends(get_db),
    current_user: User = super_admin_only,
):
    return get_subscription_health(db)