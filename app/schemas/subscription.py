# app/schemas/subscription.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.subscriptions import BillingCycle, PlanType, SubscriptionStatus


class SubscriptionCreate(BaseModel):
    tenant_id: int
    plan: PlanType = PlanType.pay_as_you_go
    billing_cycle: BillingCycle = BillingCycle.pay_as_you_go
    auto_renew: bool = True


class SubscriptionUpdate(BaseModel):
    plan: Optional[PlanType] = None
    billing_cycle: Optional[BillingCycle] = None
    status: Optional[SubscriptionStatus] = None
    auto_renew: Optional[bool] = None
    ends_at: Optional[datetime] = None
    grace_period_ends_at: Optional[datetime] = None


class SubscriptionChangePlan(BaseModel):
    """Schema for tenant plan upgrade/downgrade requests."""
    plan: PlanType
    billing_cycle: BillingCycle = BillingCycle.monthly


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
