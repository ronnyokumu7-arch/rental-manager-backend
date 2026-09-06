# app/schemas/tenant_policy.py
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.tenant_policies import PolicyCategory


class TenantPolicyCreate(BaseModel):
    category: PolicyCategory
    clause_key: Optional[str] = Field(
        None,
        max_length=60,
        description="Default clause being overridden. NULL = custom/additional clause.",
    )
    title: str = Field(..., min_length=1, max_length=255, description="Clause title")
    content: str = Field(..., min_length=1, max_length=5000, description="Clause body text")
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
    category: str
    clause_key: Optional[str] = None
    title: str
    content: str
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ✅ Merged clause view — what the contract renders and the settings page previews
class PolicyClauseOut(BaseModel):
    category: str
    clause_key: Optional[str] = None
    title: str
    content: str
    display_order: int
    is_custom: bool
    policy_id: Optional[int] = None


class CategoryLabelOut(BaseModel):
    value: str
    label: str


class PolicyDocumentOut(BaseModel):
    """Full merged document: tab metadata + the 3-category clause lists."""
    categories: List[CategoryLabelOut]
    document: Dict[str, List[PolicyClauseOut]]
