import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base, AuditMixin


class PlanType(str, enum.Enum):
    free_trial = "free_trial"
    starter_trial = "starter_trial"
    pay_as_you_go = "pay_as_you_go"
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"


class BillingCycle(str, enum.Enum):
    trial = "trial"
    pay_as_you_go = "pay_as_you_go"
    monthly = "monthly"
    annual = "annual"


class SubscriptionStatus(str, enum.Enum):
    trial = "trial"
    starter_trial = "starter_trial"
    active = "active"
    pending_verification = "pending_verification"
    past_due = "past_due"
    suspended = "suspended"
    cancelled = "cancelled"


class Subscription(Base, AuditMixin):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    
    # ✅ FIX: Removed `index=True` here to prevent conflict with the composite index below.
    # The composite index `ix_subscriptions_tenant_id` will still efficiently serve tenant lookups.
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    plan = Column(Enum(PlanType), nullable=False, default=PlanType.free_trial)
    billing_cycle = Column(Enum(BillingCycle), nullable=False, default=BillingCycle.trial)
    status = Column(
        Enum(SubscriptionStatus),
        nullable=False,
        default=SubscriptionStatus.trial,
        server_default=SubscriptionStatus.trial.value,
    )
    
    starts_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ends_at = Column(DateTime(timezone=True), nullable=True)
    grace_period_ends_at = Column(DateTime(timezone=True), nullable=True)
    
    auto_renew = Column(Boolean, nullable=False, default=True, server_default="true")
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    tenant = relationship("Tenant", back_populates="subscriptions", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES:
    __table_args__ = (
        # 1. Tenant Subscription List & "Find Latest"
        Index("ix_subscriptions_tenant_created", "tenant_id", "created_at"),
        
        # 2. Status Filtering
        Index("ix_subscriptions_tenant_status", "tenant_id", "status"),
        
        # 3. Single Subscription Lookup with Tenant Scoping (This is the one that was conflicting)
        Index("ix_subscriptions_tenant_id", "tenant_id", "id"),
        
        # 4. Expiry Checks
        Index("ix_subscriptions_status_ends_at", "status", "ends_at"),
        
        # 5. Super Admin Cross-Tenant View
        Index("ix_subscriptions_status_created", "status", "created_at"),
        
        # 6. Pending Verification Queue
        Index("ix_subscriptions_pending_verification", "status", "created_at"),
    )
