# app/routers/financials.py

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import func, extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.users import User
from app.models.invoices import Invoice, InvoiceStatus
from app.models.contracts import Contract, ContractStatus
from app.models.payments import Payment, PaymentStatus
from app.models.bookings import Booking
from app.schemas.financials import (
    FinancialOverviewOut, 
    RevenueOverview, 
    InvoiceStatusSummary, 
    ContractHealth,
    MonthlyRevenueItem,
    ActivityItem
)

router = APIRouter(prefix="/financials", tags=["financials"])

@router.get("/overview", response_model=FinancialOverviewOut)
@limiter.limit("30/minute")  # 🚨 Protects dashboard from being hammered on every page load
async def get_financial_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc)

    # =====================================================
    # 1. REVENUE OVERVIEW
    # =====================================================
    
    # Total Revenue (sum of completed payments)
    total_revenue_stmt = select(func.sum(Payment.amount)).where(
        Payment.tenant_id == tenant_id,
        Payment.status == PaymentStatus.completed
    )
    total_revenue_result = (await db.execute(total_revenue_stmt)).scalar() or Decimal("0.00")

    # Total Pending (sum of unpaid amounts on sent/partially_paid invoices)
    # ✅ FIXED: Changed Payment.tenant_id to Invoice.tenant_id (was a bug in original code)
    total_pending_stmt = select(func.sum(Invoice.amount_due - Invoice.amount_paid)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.partially_paid])
    )
    total_pending_result = (await db.execute(total_pending_stmt)).scalar() or Decimal("0.00")

    # Monthly Trend (last 6 months of revenue)
    six_months_ago = now - timedelta(days=180)
    
    monthly_revenue_stmt = select(
        extract('month', Payment.paid_at).label('month'),
        func.sum(Payment.amount).label('amount')
    ).where(
        Payment.tenant_id == tenant_id,
        Payment.status == PaymentStatus.completed,
        Payment.paid_at >= six_months_ago
    ).group_by(
        extract('month', Payment.paid_at)
    ).order_by(
        extract('month', Payment.paid_at)
    )
    
    monthly_revenue_query = (await db.execute(monthly_revenue_stmt)).all()

    month_names = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }

    monthly_trend = [
        MonthlyRevenueItem(
            month=month_names[int(row.month)],
            amount=Decimal(str(row.amount))
        )
        for row in monthly_revenue_query if row.month is not None
    ]

    avg_monthly_revenue = total_revenue_result / 6 if monthly_trend else Decimal("0.00")

    revenue_overview = RevenueOverview(
        avg_monthly_revenue=avg_monthly_revenue,
        total_revenue=total_revenue_result,
        total_pending=total_pending_result,
        monthly_trend=monthly_trend
    )

    # =====================================================
    # 2. INVOICE STATUS SUMMARY
    # =====================================================
    
    paid_count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status == InvoiceStatus.paid
    )
    paid_count = (await db.execute(paid_count_stmt)).scalar() or 0

    pending_count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.partially_paid])
    )
    pending_count = (await db.execute(pending_count_stmt)).scalar() or 0

    overdue_count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status == InvoiceStatus.overdue
    )
    overdue_count = (await db.execute(overdue_count_stmt)).scalar() or 0

    total_invoices = paid_count + pending_count + overdue_count

    paid_percentage = (paid_count / total_invoices * 100) if total_invoices > 0 else 0.0
    pending_percentage = (pending_count / total_invoices * 100) if total_invoices > 0 else 0.0
    overdue_percentage = (overdue_count / total_invoices * 100) if total_invoices > 0 else 0.0
    collection_rate = (paid_count / total_invoices * 100) if total_invoices > 0 else 0.0

    invoice_status = InvoiceStatusSummary(
        paid_count=paid_count,
        pending_count=pending_count,
        overdue_count=overdue_count,
        paid_percentage=round(paid_percentage, 1),
        pending_percentage=round(pending_percentage, 1),
        overdue_percentage=round(overdue_percentage, 1),
        collection_rate=round(collection_rate, 1)
    )

    # =====================================================
    # 3. CONTRACT HEALTH
    # =====================================================
    
    signed_count_stmt = select(func.count(Contract.id)).where(
        Contract.tenant_id == tenant_id,
        Contract.status == ContractStatus.signed
    )
    signed_count = (await db.execute(signed_count_stmt)).scalar() or 0

    draft_count_stmt = select(func.count(Contract.id)).where(
        Contract.tenant_id == tenant_id,
        Contract.status == ContractStatus.draft
    )
    draft_count = (await db.execute(draft_count_stmt)).scalar() or 0

    sent_count_stmt = select(func.count(Contract.id)).where(
        Contract.tenant_id == tenant_id,
        Contract.status == ContractStatus.sent
    )
    sent_count = (await db.execute(sent_count_stmt)).scalar() or 0

    total_contracts = signed_count + draft_count + sent_count

    signed_percentage = (signed_count / total_contracts * 100) if total_contracts > 0 else 0.0
    draft_percentage = (draft_count / total_contracts * 100) if total_contracts > 0 else 0.0
    sent_percentage = (sent_count / total_contracts * 100) if total_contracts > 0 else 0.0

    contract_health = ContractHealth(
        signed_count=signed_count,
        draft_count=draft_count,
        sent_count=sent_count,
        signed_percentage=round(signed_percentage, 1),
        draft_percentage=round(draft_percentage, 1),
        sent_percentage=round(sent_percentage, 1),
        total_active=signed_count
    )

    # =====================================================
    # 4. RECENT ACTIVITY
    # =====================================================
    
    activities: List[ActivityItem] = []

    # Fetch recent payments (last 3) using async outer joins
    recent_payments_stmt = select(
        Payment, Invoice.invoice_number, Booking.id.label('booking_id')
    ).outerjoin(
        Invoice, Payment.invoice_id == Invoice.id
    ).outerjoin(
        Booking, Invoice.booking_id == Booking.id
    ).where(
        Payment.tenant_id == tenant_id,
        Payment.status == PaymentStatus.completed
    ).order_by(Payment.paid_at.desc()).limit(3)
    
    recent_payments_result = (await db.execute(recent_payments_stmt)).all()

    for p, inv_num, booking_id in recent_payments_result:
        ref_text = f"({p.reference})" if p.reference else ""
        activities.append(ActivityItem(
            id=f"pay_{p.id}",
            type="payment_received",
            title="Payment Received",
            description=f"KES {p.amount:,.2f} {ref_text}",
            timestamp=p.paid_at or p.created_at,
            link=f"/dashboard/bookings/{booking_id}" if booking_id else "/dashboard/payments"
        ))

    # Fetch recent signed contracts (last 2)
    recent_contracts_stmt = select(
        Contract, Booking.id.label('booking_id')
    ).join(
        Booking, Contract.booking_id == Booking.id
    ).where(
        Contract.tenant_id == tenant_id,
        Contract.status == ContractStatus.signed
    ).order_by(Contract.client_signed_at.desc()).limit(2)
    
    recent_contracts_result = (await db.execute(recent_contracts_stmt)).all()

    for c, booking_id in recent_contracts_result:
        activities.append(ActivityItem(
            id=f"con_{c.id}",
            type="contract_signed",
            title="Contract Signed",
            description=f"Contract #{c.contract_number} signed",
            timestamp=c.client_signed_at or c.created_at,
            link=f"/dashboard/bookings/{booking_id}"
        ))

    # Sort by timestamp and take top 5 (filter out any None timestamps just in case)
    valid_activities = [a for a in activities if a.timestamp is not None]
    valid_activities.sort(key=lambda x: x.timestamp, reverse=True)
    recent_activity = valid_activities[:5]

    # =====================================================
    # RETURN COMBINED RESPONSE
    # =====================================================
    
    return FinancialOverviewOut(
        revenue_overview=revenue_overview,
        invoice_status=invoice_status,
        contract_health=contract_health,
        recent_activity=recent_activity
    )
