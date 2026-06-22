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
    share_token: Optional[str] = None
    share_token_expires_at: Optional[datetime] = None
    signed_by_client: bool = False
    client_signed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class PublicContractView(BaseModel):
    """Schema for public contract viewing (no auth required)"""
    contract_number: str
    booking_id: int
    tenant_name: str
    client_name: str
    vehicle_make: str
    vehicle_model: str
    vehicle_plate: str
    start_date: str
    end_date: str
    total_amount: str
    currency_code: str
    status: ContractStatus
    signed_by_client: bool
    created_at: datetime
