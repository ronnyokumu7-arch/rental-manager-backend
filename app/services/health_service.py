# app/services/health_service.py

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.models.bookings import Booking
from app.models.vehicles import Vehicle
from app.models.invoices import Invoice


class HealthService:
    @staticmethod
    async def get_agency_health(db: AsyncSession, tenant_id: int) -> dict:
        """
        Returns privacy-safe aggregate health metrics for a specific tenant.
        No PII, no specific booking/client details are exposed.
        """
        # ✅ FIXED: Use timezone-aware UTC datetime to prevent PostgreSQL comparison errors
        now = datetime.now(timezone.utc)
        last_7_days = now - timedelta(days=7)
        last_30_days = now - timedelta(days=30)

        # 1. Activity Pulse (Aggregate Login Counts)
        # ✅ FIXED: Split into two clean async queries (original syntax was invalid in SQLAlchemy 2.0)
        logins_7d_stmt = select(func.count(func.distinct(User.id))).where(
            User.tenant_id == tenant_id,
            User.last_login_at >= last_7_days
        )
        logins_7d = (await db.execute(logins_7d_stmt)).scalar() or 0

        logins_30d_stmt = select(func.count(func.distinct(User.id))).where(
            User.tenant_id == tenant_id,
            User.last_login_at >= last_30_days
        )
        logins_30d = (await db.execute(logins_30d_stmt)).scalar() or 0

        active_sessions_stmt = select(func.avg(User.avg_session_duration_minutes)).where(
            User.tenant_id == tenant_id, 
            User.last_login_at >= last_30_days
        )
        active_sessions = (await db.execute(active_sessions_stmt)).scalar() or 0

        # 2. Fleet Utilization (Asset Efficiency)
        total_vehicles_stmt = select(func.count(Vehicle.id)).where(Vehicle.tenant_id == tenant_id)
        total_vehicles = (await db.execute(total_vehicles_stmt)).scalar() or 0
        
        active_vehicles_stmt = select(func.count(func.distinct(Booking.vehicle_id))).where(
            Booking.tenant_id == tenant_id,
            Booking.start_date <= now,
            Booking.end_date >= now
        )
        active_vehicles = (await db.execute(active_vehicles_stmt)).scalar() or 0
        
        utilization_pct = round((active_vehicles / total_vehicles * 100), 1) if total_vehicles > 0 else 0

        # 3. Revenue Velocity (Booking Momentum - Counts Only)
        bookings_this_week_stmt = select(func.count(Booking.id)).where(
            Booking.tenant_id == tenant_id,
            Booking.created_at >= last_7_days
        )
        bookings_this_week = (await db.execute(bookings_this_week_stmt)).scalar() or 0

        bookings_last_week_stmt = select(func.count(Booking.id)).where(
            Booking.tenant_id == tenant_id,
            Booking.created_at >= last_7_days - timedelta(days=7),
            Booking.created_at < last_7_days
        )
        bookings_last_week = (await db.execute(bookings_last_week_stmt)).scalar() or 0

        # 4. Payment Reliability (Financial Trust)
        total_paid_stmt = select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == 'paid'
        )
        total_paid = (await db.execute(total_paid_stmt)).scalar() or 0

        overdue_count_stmt = select(func.count(Invoice.id)).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == 'overdue',
            Invoice.due_date < now
        )
        overdue_count = (await db.execute(overdue_count_stmt)).scalar() or 0

        on_time_rate = round(((total_paid - overdue_count) / total_paid * 100), 1) if total_paid > 0 else 100.0

        # 5. Composite Health Score Calculation (0-100)
        score = 0
        score += min(utilization_pct * 0.3, 30)          # 30% weight: Asset efficiency
        score += min(on_time_rate * 0.3, 30)             # 30% weight: Financial reliability  
        score += min((bookings_this_week / max(bookings_last_week, 1)) * 20, 20) # 20% weight: Growth momentum
        score += min((logins_7d / 7) * 2, 20)            # 20% weight: Platform engagement
        
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
                "lastActiveAt": None,
                "avgSessionDurationMinutes": round(float(active_sessions), 1) if active_sessions else 0
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
