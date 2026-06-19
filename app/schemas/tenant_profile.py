from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class TenantProfileCreate(BaseModel):
    company_name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None
    tax_number: Optional[str] = None
    contract_footer: Optional[str] = None


class TenantProfileUpdate(BaseModel):
    company_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None
    tax_number: Optional[str] = None
    contract_footer: Optional[str] = None


class TenantProfileOut(BaseModel):
    id: int
    tenant_id: int
    company_name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None
    tax_number: Optional[str] = None
    logo_url: Optional[str] = None
    contract_prefix: str
    contract_footer: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}