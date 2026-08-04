# backend/app/schemas/financials.py
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel

class MonthlyRevenueItem(BaseModel):
    month: str  # e.g., "Jan", "Feb"
    amount: Decimal

class RevenueOverview(BaseModel):
    avg_monthly_revenue: Decimal
    total_revenue: Decimal
    total_pending: Decimal
    monthly_trend: List[MonthlyRevenueItem]

class InvoiceStatusSummary(BaseModel):
    paid_count: int
    pending_count: int
    overdue_count: int
    paid_percentage: float
    pending_percentage: float
    overdue_percentage: float
    collection_rate: float

class ContractHealth(BaseModel):
    signed_count: int
    draft_count: int
    sent_count: int
    signed_percentage: float
    draft_percentage: float
    sent_percentage: float
    total_active: int

class ActivityItem(BaseModel):
    id: str
    type: str  # e.g., "payment_received", "contract_signed"
    title: str
    description: str
    timestamp: datetime
    link: str

class FinancialOverviewOut(BaseModel):
    revenue_overview: RevenueOverview
    invoice_status: InvoiceStatusSummary
    contract_health: ContractHealth
    recent_activity: List[ActivityItem]
