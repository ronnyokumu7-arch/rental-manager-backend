import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class SubscriptionStatus(str, enum.Enum):
    trial = "trial"
    starter_trial = "starter_trial"
    active = "active"
    past_due = "past_due"
    suspended = "suspended"
    cancelled = "cancelled"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False)
    phone_number = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    plan = Column(String, nullable=False, default="free_trial", server_default="free_trial")
    subscription_status = Column(
        Enum(SubscriptionStatus),
        nullable=False,
        default=SubscriptionStatus.trial,
        server_default=SubscriptionStatus.trial.value,
    )
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    grace_period_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="tenant", cascade="all, delete-orphan")
    vehicles = relationship("Vehicle", back_populates="tenant", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="tenant", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="tenant", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="tenant", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="tenant", cascade="all, delete-orphan")
    profile = relationship("TenantProfile", back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    policies = relationship("TenantPolicy", back_populates="tenant", cascade="all, delete-orphan")
    contracts = relationship("Contract", back_populates="tenant", cascade="all, delete-orphan")