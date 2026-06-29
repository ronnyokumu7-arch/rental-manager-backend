from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, Field
from app.models.tenants import SubscriptionStatus

class TenantBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = Field(default=None, max_length=50)
    plan: Literal["free_trial", "starter_trial", "starter", "pro", "enterprise"] = "free_trial"
    is_active: bool = True

class TenantCreate(TenantBase):
    pass

class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = Field(default=None, max_length=50)
    plan: Optional[Literal["free_trial", "starter_trial", "starter", "pro", "enterprise"]] = None
    is_active: Optional[bool] = None

class TenantOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone_number: Optional[str] = None
    plan: str
    is_active: bool
    subscription_status: Optional[SubscriptionStatus] = None
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None
    grace_period_ends_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
