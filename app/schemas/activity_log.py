"""
Activity log schemas for audit trail viewing.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActivityLogOut(BaseModel):
    """
    Output schema for activity logs.
    Includes tenant_id for multi-tenancy transparency.
    """
    id: int
    tenant_id: int
    user_id: Optional[int] = None  # ✅ Nullable for audit preservation (user deleted)
    action: str = Field(..., max_length=100)
    target_type: Optional[str] = Field(default=None, max_length=50)
    target_id: Optional[int] = None
    details: Optional[dict] = None
    created_at: datetime
    
    model_config = {"from_attributes": True}
    
