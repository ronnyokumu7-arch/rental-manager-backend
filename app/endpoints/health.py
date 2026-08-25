# app/routers/endpoints/health.py (or wherever this file lives)

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.rbac import require_role
from app.models.users import User, UserRole
from app.models.bookings import Booking
from app.models.vehicles import Vehicle
from app.models.invoices import Invoice

router = APIRouter(prefix="/tenants", tags=["Agency Health"])


@router.get("/{tenant_id}/health")
@limiter.limit("30/minute")  # 🚨 Heavy endpoint: 9+ aggregate queries per call
async def get_agency_health(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.super_admin]))
):
    # ✅ FIXED: Use timezone-aware UTC datetime to prevent PostgreSQL comparison errors
    now = datetime.now(timezone.utc)
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)
    
    try:
        # 1. Logins last 7 days
        logins_7d_stmt = select(func.count(func.distinct(User.id))).where(
            User.tenant_id == tenant_id,
            User.last_login_at >= last_7_days
        )
        logins_7d = (await db.execute(logins_7d_stmt)).scalar() or 0

        # 2. Logins last 30 days
        logins_30d_stmt = select(func.count(func.distinct(User.id))).where(
            User.tenant_id == tenant_id,
            User.last_login_at >= last_30_days
        )
        logins_30d = (await db.execute(logins_30d_stmt)).scalar() or 0
        
        # 3. Last active timestamp
        last_active_stmt = select(User.last_login_at).where(
            User.tenant_id == tenant_id,
            User.last_login_at.isnot(None)
        ).order_by(User.last_login_at.desc()).limit(1)
        last_active = (await db.execute(last_active_stmt)).first()
        last_active_at = last_active[0].isoformat() if last_active else None

        # 4. Total vehicles
        total_vehicles_stmt = select(func.count(Vehicle.id)).where(
            Vehicle.tenant_id == tenant_id
        )
        total_vehicles = (await db.execute(total_vehicles_stmt)).scalar() or 0
        
        # 5. Active vehicles (currently rented)
        active_vehicles_stmt = select(func.count(func.distinct(Booking.vehicle_id))).where(
            Booking.tenant_id == tenant_id,
            Booking.start_date <= now,
            Booking.end_date >= now
        )
        active_vehicles = (await db.execute(active_vehicles_stmt)).scalar() or 0
        
        utilization_pct = round((active_vehicles / total_vehicles * 100), 1) if total_vehicles > 0 else 0

        # 6. Bookings this week
        bookings_this_week_stmt = select(func.count(Booking.id)).where(
            Booking.tenant_id == tenant_id,
            Booking.created_at >= last_7_days
        )
        bookings_this_week = (await db.execute(bookings_this_week_stmt)).scalar() or 0
        
        # 7. Bookings last week
        bookings_last_week_stmt = select(func.count(Booking.id)).where(
            Booking.tenant_id == tenant_id,
            Booking.created_at >= last_7_days - timedelta(days=7),
            Booking.created_at < last_7_days
        )
        bookings_last_week = (await db.execute(bookings_last_week_stmt)).scalar() or 0

        # 8. Total paid invoices
        total_paid_stmt = select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == 'paid'
        )
        total_paid = (await db.execute(total_paid_stmt)).scalar() or 0
        
        # 9. Overdue invoices
        overdue_count_stmt = select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == 'overdue',
            Invoice.due_date < now
        )
        overdue_count = (await db.execute(overdue_count_stmt)).scalar() or 0
        
        on_time_rate = round(((total_paid - overdue_count) / total_paid * 100), 1) if total_paid > 0 else 100.0

        # 10. Calculate health score
        score = 0
        score += min(utilization_pct * 0.3, 30)          
        score += min(on_time_rate * 0.3, 30)             
        score += min((bookings_this_week / max(bookings_last_week, 1)) * 20, 20) 
        score += min((logins_7d / 7) * 2, 20) 
        
        risk_level = "low" if score >= 70 else "medium" if score >= 40 else "high"
        trend = "up" if bookings_this_week > bookings_last_week else "down" if bookings_this_week < bookings_last_week else "stable"

        return {
            "score": {
                "score": round(score),
                "riskLevel": risk_level,
                "trend": trend,
                "lastCalculatedAt": now.isoformat()
            },
            "activity": {
                "loginsLast7Days": logins_7d,
                "loginsLast30Days": logins_30d,
                "activeDaysThisMonth": 0,
                "lastActiveAt": last_active_at,
                "avgSessionDurationMinutes": 0
            },
            "utilization": {
                "totalVehicles": total_vehicles,
                "activeVehicles": active_vehicles,
                "utilizationPercentage": utilization_pct,
                "idleVehiclesCount": total_vehicles - active_vehicles
            },
            "revenueVelocity": {
                "bookingsThisWeek": bookings_this_week,
                "bookingsLastWeek": bookings_last_week,
                "bookingsThisMonth": 0,
                "trend": trend,
                "weeklyData": []
            },
            "paymentReliability": {
                "currentStreak": 0,
                "onTimePaymentRate": on_time_rate,
                "totalInvoicesPaid": total_paid,
                "overdueInvoicesCount": overdue_count
            },
            "featureAdoption": {
                "modulesUsed": [],
                "totalAvailableModules": 6,
                "adoptionPercentage": 0,
                "mostUsedModule": "bookings",
                "leastUsedModule": None
            },
            "supportTickets": {
                "openTickets": 0,
                "closedThisMonth": 0,
                "avgResolutionTimeHours": 0,
                "trend": "stable"
            }
        }
    except Exception as e:
        print(f"HEALTH ENDPOINT ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to calculate health metrics: {str(e)}")
