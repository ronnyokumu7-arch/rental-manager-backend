from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.subscriptions import BillingCycle, PlanType, SubscriptionStatus


class SubscriptionCreate(BaseModel):
    tenant_id: int
    plan: PlanType = PlanType.free_trial
    billing_cycle: BillingCycle = BillingCycle.trial
    auto_renew: bool = True


class SubscriptionUpdate(BaseModel):
    auto_renew: Optional[bool] = None
    ends_at: Optional[datetime] = None
    grace_period_ends_at: Optional[datetime] = None


class SubscriptionOut(BaseModel):
    id: int
    tenant_id: int
    plan: PlanType
    billing_cycle: BillingCycle
    status: SubscriptionStatus
    starts_at: datetime
    ends_at: Optional[datetime] = None
    grace_period_ends_at: Optional[datetime] = None
    auto_renew: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}