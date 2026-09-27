import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class InvestorContractStatus(str, enum.Enum):
    draft = "draft"
    pending_signature = "pending_signature"
    signed = "signed"
    terminated = "terminated"


class InvestorContract(Base, AuditMixin):
    __tablename__ = "investor_contracts"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # ✅ UPDATED: Removed unique=True. A vehicle can have many daily contracts over time.
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # ✅ NEW: Links daily contracts to a specific rental booking. Null for monthly contracts.
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    
    contract_number = Column(String(50), nullable=False)
    
    # Lease Terms Snapshot
    lease_rate = Column(Numeric(10, 2), nullable=False)
    lease_rate_type = Column(String(20), nullable=False)  # 'daily' or 'monthly'
    duration_months = Column(Integer, nullable=True)      # Only used for monthly contracts
    
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    
    status = Column(
        Enum(InvestorContractStatus),
        nullable=False,
        default=InvestorContractStatus.draft,
        server_default=InvestorContractStatus.draft.value,
    )
    
    # Document Storage
    pdf_path = Column(String(500), nullable=True)
    
    # Public Sharing & Remote Signing
    share_token = Column(String(36), unique=True, nullable=True, index=True)
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Investor Signature Tracking
    signed_by_investor = Column(Boolean, nullable=False, default=False, server_default="false")
    investor_signed_at = Column(DateTime(timezone=True), nullable=True)
    investor_signature_path = Column(String(500), nullable=True)  # ✅ ADDED for storage backend resolution
    
    # ✅ Agency Signature Tracking
    signed_by_agency = Column(Boolean, nullable=False, default=False, server_default="false")
    agency_signed_at = Column(DateTime(timezone=True), nullable=True)
    agency_signature_path = Column(String(500), nullable=True)    # ✅ ADDED for storage backend resolution

    # Relationships
    tenant = relationship("Tenant", back_populates="investor_contracts", foreign_keys=[tenant_id])
    vehicle = relationship("Vehicle", back_populates="investor_contracts", foreign_keys=[vehicle_id])
    booking = relationship("Booking", back_populates="investor_contracts", foreign_keys=[booking_id])

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_number", name="uq_tenant_investor_contract_number"),
        Index("ix_investor_contracts_tenant_created", "tenant_id", "created_at"),
        Index("ix_investor_contracts_tenant_status", "tenant_id", "status"),
        Index("ix_investor_contracts_vehicle_id", "vehicle_id"),
        Index("ix_investor_contracts_booking_id", "booking_id"),
        Index("ix_investor_contracts_token_expires", "share_token", "share_token_expires_at"),
    )
