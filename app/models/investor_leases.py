from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, Enum, Numeric, ForeignKey, text
from sqlalchemy.orm import relationship
from app.db.database import Base
import enum

class LeaseType(str, enum.Enum):
    pay_per_booking = "pay_per_booking" # Fixed rate per day when booked
    fixed_monthly = "fixed_monthly"     # Flat fee every month

class LeaseStatus(str, enum.Enum):
    draft = "draft"
    pending_signature = "pending_signature"
    active = "active"
    terminated = "terminated"

class InvestorLease(Base):
    __tablename__ = "investor_leases"

    id = Column(Integer, primary_key=True, index=True)
    
    # ✅ Matched ondelete rules to Alembic migration
    investor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False) # The Agency
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True) # Linked later

    # Lease Details
    lease_type = Column(Enum(LeaseType), nullable=False)
    
    # ✅ CRITICAL: Numeric(10, 2) for exact currency precision. Never use Float for money.
    rate_amount = Column(Numeric(10, 2), nullable=False) # e.g., 3000 KES per day OR 50,000 KES per month
    duration_months = Column(Integer, nullable=False) # 3, 6, 12
    
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    # Signatures
    investor_signed_at = Column(DateTime(timezone=True), nullable=True)
    agency_signed_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Matched server_defaults to Alembic migration
    status = Column(Enum(LeaseStatus), nullable=False, default=LeaseStatus.draft, server_default=LeaseStatus.draft.value)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=text("now()"))

    # Relationships
    investor = relationship("User", foreign_keys=[investor_id])
    tenant = relationship("Tenant")
    vehicle = relationship("Vehicle")
