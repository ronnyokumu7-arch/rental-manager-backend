import enum
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, String, Index, UniqueConstraint, JSON
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
    share_token = Column(String(36), unique=True, nullable=True, index=True)
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Client Signature Tracking (Terms & Conditions)
    signed_by_client = Column(Boolean, nullable=False, default=False, server_default="false")
    client_signed_at = Column(DateTime(timezone=True), nullable=True)

    # ✅ NEW: Handover Checklist & Second Signature
    # 1. Snapshot of vehicle features at the time of contract creation (e.g., ["Spare Wheel", "Jack"])
    handover_items = Column(JSON, nullable=True, server_default="[]")
    # 2. The client's actual tick-box selections during signing (e.g., {"Spare Wheel": true, "Jack": false})
    handover_checklist = Column(JSON, nullable=True)
    # 3. The image URL of the client's signature for the handover checklist
    handover_signature_image_path = Column(String(500), nullable=True)
    # 4. Timestamp of when the client signed the handover checklist
    handover_signed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    booking = relationship("Booking", back_populates="contract", foreign_keys=[booking_id])
    tenant = relationship("Tenant", back_populates="contracts", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_number", name="uq_tenant_contract_number"),
        Index("ix_contracts_tenant_created", "tenant_id", "created_at"),
        Index("ix_contracts_tenant_status", "tenant_id", "status"),
        Index("ix_contracts_tenant_id", "tenant_id", "id"),
        Index("ix_contracts_token_expires", "share_token", "share_token_expires_at"),
        Index("ix_contracts_tenant_signed", "tenant_id", "status", "client_signed_at"),
    )
