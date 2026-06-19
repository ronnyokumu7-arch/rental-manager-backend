from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.contracts import ContractStatus


class ContractOut(BaseModel):
    id: int
    booking_id: int
    tenant_id: int
    contract_number: str
    status: ContractStatus
    pdf_path: Optional[str] = None
    signed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}