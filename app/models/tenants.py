import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, JSON, Text, Index
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin

# ✅ CRITICAL FIX: Use TYPE_CHECKING to prevent circular imports at runtime.
if TYPE_CHECKING:
    from app.models.payment_gateways.airtel import AirtelMoneyConfig
    from app.models.payment_gateways.stripe import StripeConfig
    from app.models.payment_gateways.paypal import PaypalConfig
    from app.models.payment_gateways.mpesa import MpesaConfig
    from app.models.payment_gateways.bank import BankAccountConfig


class SubscriptionStatus(str, enum.Enum):
    trial = "trial"
    starter_trial = "starter_trial"
    active = "active"
    pending_verification = "pending_verification"
    past_due = "past_due"
    suspended = "suspended"
    cancelled = "cancelled"


class PaymentMethodType(str, enum.Enum):
    mpesa = "mpesa"
    airtel_money = "airtel_money"
    card = "card"
    paypal = "paypal"
    bank = "bank"


class Tenant(Base, AuditMixin):
    __tablename__ = "tenants"

    # Primary Keys & Identity
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone_number = Column(String(30), nullable=True)

    # Agency Owner
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Denormalized Admin Snapshot
    admin_name = Column(String(150), nullable=True)
    admin_email = Column(String(255), nullable=True)
    admin_phone = Column(String(30), nullable=True)

    # Lifecycle & Multi-Tenancy
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    suspension_reason = Column(Text, nullable=True)

    # Recovery & Audit Trail
    last_reset_request_at = Column(DateTime(timezone=True), nullable=True)
    email_change_cooldown_until = Column(DateTime(timezone=True), nullable=True)
    admin_email_changed_at = Column(DateTime(timezone=True), nullable=True)
    admin_changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Subscription & Billing
    plan = Column(String(50), nullable=False, default="free_trial", server_default="free_trial")
    subscription_status = Column(
        Enum(SubscriptionStatus),
        nullable=False,
        default=SubscriptionStatus.trial,
        server_default=SubscriptionStatus.trial.value,
    )

    billing_cycle = Column(String(20), nullable=False, default="monthly", server_default="monthly")
    auto_renew = Column(Boolean, nullable=False, default=True, server_default="true")
    custom_vehicle_limit = Column(Integer, nullable=True)

    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    grace_period_ends_at = Column(DateTime(timezone=True), nullable=True)

    # Payment Gateway Readiness
    default_payment_method = Column(Enum(PaymentMethodType), nullable=True)
    stripe_customer_id = Column(String(100), nullable=True, index=True)
    paypal_payer_id = Column(String(100), nullable=True)
    payment_metadata = Column(JSON, nullable=True)

    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # ========================================================================
    # RELATIONSHIPS (All back_populates must match the child model exactly)
    # ========================================================================
    # ✅ FIX: Explicitly use owner_id to avoid ambiguity with admin_changed_by_user_id and AuditMixin.created_by
    owner = relationship("User", foreign_keys=[owner_id], uselist=False)
    
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan", foreign_keys="[User.tenant_id]")
    
    clients = relationship("Client", back_populates="tenant", cascade="all, delete-orphan")
    vehicles = relationship("Vehicle", back_populates="tenant", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="tenant", cascade="all, delete-orphan")
    
    payment_verifications = relationship("PaymentVerification", back_populates="tenant", cascade="all, delete-orphan")

    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="tenant", cascade="all, delete-orphan")
    
    profile = relationship("TenantProfile", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    policies = relationship("TenantPolicy", back_populates="tenant", cascade="all, delete-orphan")
    contracts = relationship("Contract", back_populates="tenant", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="tenant", cascade="all, delete-orphan")
    
    # ✅ ADDED: These were missing and causing the mapper errors
    activity_logs = relationship("ActivityLog", back_populates="tenant", cascade="all, delete-orphan")
    role_templates = relationship("RoleTemplate", back_populates="tenant", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="tenant", cascade="all, delete-orphan")

    # ✅ Payment Gateways: String literals resolve at runtime.
    mpesa_config = relationship("MpesaConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    airtel_config = relationship("AirtelMoneyConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    bank_accounts = relationship("BankAccountConfig", back_populates="tenant", cascade="all, delete-orphan")
    stripe_config = relationship("StripeConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    paypal_config = relationship("PaypalConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")

    # ✅ OPTIMIZED INDEXES:
    __table_args__ = (
        Index("ix_tenants_active_list", "is_archived", "is_active", "created_at"),
        Index("ix_tenants_subscription_status", "subscription_status", "is_archived"),
        Index("ix_tenants_subscription_expiry", "subscription_status", "subscription_ends_at"),
    )
