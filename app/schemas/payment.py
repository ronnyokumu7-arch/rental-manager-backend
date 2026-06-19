from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.payments import PaymentMethod, PaymentStatus


class PaymentCreate(BaseModel):
    invoice_id: int
    amount: Decimal
    currency_code: str = "KES"
    method: PaymentMethod
    reference: Optional[str] = None
    notes: Optional[str] = None


class PaymentOut(BaseModel):
    id: int
    invoice_id: int
    tenant_id: int
    amount: Decimal
    currency_code: str
    method: PaymentMethod
    reference: Optional[str] = None
    status: PaymentStatus
    paid_at: Optional[datetime] = None
    recorded_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}