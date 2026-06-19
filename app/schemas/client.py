from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.clients import ClientStatus


class ClientBase(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    phone: str
    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None
    status: Optional[ClientStatus] = None


class ClientOut(BaseModel):
    id: int
    tenant_id: int
    full_name: str
    email: Optional[EmailStr] = None
    phone: str
    id_number: Optional[str] = None
    status: ClientStatus
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}