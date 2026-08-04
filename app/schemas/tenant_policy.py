from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.tenant_policies import PolicySection


class TenantPolicyCreate(BaseModel):
    section: PolicySection
    title: str = Field(..., min_length=1, max_length=255, description="Policy title")
    content: str = Field(..., min_length=1, max_length=5000, description="Policy body text")
    is_active: bool = True
    display_order: int = 0


class TenantPolicyUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class TenantPolicyOut(BaseModel):
    id: int
    tenant_id: int
    section: PolicySection
    title: str
    content: str
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
