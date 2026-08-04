import enum
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, String, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base, AuditMixin


class ContractStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    signed = "signed"
    void = "void"


class Contract(Base, AuditMixin):
    __tablename__ = "contracts"
    
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # ✅ Core Identity (Tenant-scoped, monthly-resetting format: C{YYYY}{MM}{###})
    # Example: C202607001 (Contract, July 2026, #1 for this tenant)
    # Max capacity: 999 contracts per tenant per month
    contract_number = Column(String(50), nullable=False)
    
    signature_image_path = Column(String(500), nullable=True)
    
    status = Column(
        Enum(ContractStatus),
        nullable=False,
        default=ContractStatus.draft,
        server_default=ContractStatus.draft.value,
    )
    
    # Document Storage
    pdf_path = Column(String(500), nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Public Sharing & Remote Signing
    share_token = Column(String(36), unique=True, nullable=True, index=True)  # UUID format
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Client Signature Tracking
    signed_by_client = Column(Boolean, nullable=False, default=False, server_default="false")
    client_signed_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin
    booking = relationship("Booking", back_populates="contract", foreign_keys=[booking_id])
    tenant = relationship("Tenant", back_populates="contracts", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # ✅ Tenant-scoped contract number uniqueness (monthly reset per tenant)
        UniqueConstraint("tenant_id", "contract_number", name="uq_tenant_contract_number"),
        
        # 1. Contract List View (MOST IMPORTANT)
        Index("ix_contracts_tenant_created", "tenant_id", "created_at"),
        
        # 2. Status Filtering
        Index("ix_contracts_tenant_status", "tenant_id", "status"),
        
        # 3. Tenant-Scoped Contract Lookup
        Index("ix_contracts_tenant_id", "tenant_id", "id"),
        
        # 4. Public Token Lookup with Expiry Check
        Index("ix_contracts_token_expires", "share_token", "share_token_expires_at"),
        
        # 5. Signed Contracts Tracking
        Index("ix_contracts_tenant_signed", "tenant_id", "status", "client_signed_at"),
    )
