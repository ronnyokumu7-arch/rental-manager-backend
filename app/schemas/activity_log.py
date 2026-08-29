"""
Activity log schemas for audit trail viewing.
"""
from datetime import datetime
from typing import Optional, Any, Dict

from pydantic import BaseModel, Field


class ActivityLogOut(BaseModel):
    """
    Output schema for activity logs.
    Includes tenant_id for multi-tenancy transparency.
    
    ✅ UPGRADED: Added `label`, `summary`, and `priority` to enable 
    instant rendering in the premium UI without lazy-loading.
    """
    id: int
    tenant_id: int
    user_id: Optional[int] = None  # ✅ Nullable for audit preservation (user deleted)
    
    # ✅ Machine-readable action (e.g., "payment_received", "trip_overdue")
    action: str = Field(..., max_length=100)
    
    # ✅ Human-readable label (e.g., "Payment Received", "Trip Overdue")
    label: str = Field(..., max_length=255)
    
    target_type: Optional[str] = Field(default=None, max_length=50)
    target_id: Optional[int] = None
    
    # ✅ Denormalized summary for instant frontend rendering
    # Example: {"client_name": "John Doe", "client_phone": "0712345678", 
    #           "amount": "KES 11,000", "ref": "QWERTYPA01", "plate_number": "KDX 563C"}
    summary: Optional[Dict[str, Any]] = None
    
    # ✅ Detailed JSON details for flexible metadata storage
    details: Optional[Dict[str, Any]] = None
    
    # ✅ Priority level for Dashboard feed (1=Low, 2=Normal, 3=High, 4=Critical)
    priority: int = Field(default=2, ge=1, le=4)
    
    created_at: datetime
    
    model_config = {"from_attributes": True}


class ActivityLogCreate(BaseModel):
    """
    Input schema for creating activity logs (Internal use only).
    This is only used by backend services, not exposed to the frontend directly.
    """
    tenant_id: int
    user_id: Optional[int] = None
    action: str = Field(..., max_length=100)
    label: str = Field(..., max_length=255)
    target_type: Optional[str] = Field(default=None, max_length=50)
    target_id: Optional[int] = None
    summary: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    priority: int = Field(default=2, ge=1, le=4)


class ActivityLogList(BaseModel):
    """
    Output schema for a paginated list of activity logs.
    """
    items: list[ActivityLogOut]
    total: int
    page: int
    page_size: int
    pages: int
