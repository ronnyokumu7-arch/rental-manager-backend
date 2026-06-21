from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr
from app.models.clients import ClientStatus

class ClientBase(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    phone: str
    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None  # ADD THIS
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
    dl_expiry: Optional[date] = None  # ADD THIS
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
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None  # ADD THIS
    status: ClientStatus
    residential_address: Optional[str] = None
    work_address: Optional[str] = None
    next_of_kin_name: Optional[str] = None
    next_of_kin_phone: Optional[str] = None
    avatar_image: Optional[str] = None
    id_image_front: Optional[str] = None
    id_image_back: Optional[str] = None
    dl_image_front: Optional[str] = None
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}