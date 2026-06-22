import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base

class ContractStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    signed = "signed"
    void = "void"

class Contract(Base):
    __tablename__ = "contracts"
    
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_number = Column(String, unique=True, nullable=False)
    status = Column(
        Enum(ContractStatus),
        nullable=False,
        default=ContractStatus.draft,
        server_default=ContractStatus.draft.value,
    )
    pdf_path = Column(String, nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    
    # NEW: Contract sharing fields
    share_token = Column(String(36), unique=True, nullable=True, index=True)
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    signed_by_client = Column(Boolean, nullable=False, default=False, server_default="false")
    client_signed_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    booking = relationship("Booking", back_populates="contract")
    tenant = relationship("Tenant", back_populates="contracts")