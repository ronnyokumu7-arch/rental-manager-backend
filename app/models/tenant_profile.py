from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class TenantProfile(Base, AuditMixin):
    __tablename__ = "tenant_profiles"

    id = Column(Integer, primary_key=True, index=True)
    
    # One-to-one relationship with Tenant (CASCADE ensures profile is deleted when tenant is removed)
    tenant_id = Column(
        Integer, 
        ForeignKey("tenants.id", ondelete="CASCADE"), 
        nullable=False, 
        unique=True, 
        index=True
    )
    
    # Identity & Contact (Mirrors Tenant base fields for contract/invoice generation)
    company_name = Column(String(150), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    
    # Compliance & Taxation
    tax_number = Column(String(20), nullable=True)
    
    # Branding & Contracts
    logo_url = Column(Text, nullable=True)
    contract_prefix = Column(String(10), nullable=False, default="T0000")
    contract_footer = Column(Text, nullable=True)

    # ✅ NEW: Payment Methods (M-Pesa, Airtel Money & Bank).
    # All nullable — the public invoice renders ONLY configured channels
    # and never fabricates payment details (no platform fallbacks).
    mpesa_paybill = Column(String(10), nullable=True)          # PayBill business number
    mpesa_paybill_account = Column(String(50), nullable=True)  # Account quoted on PayBill
    mpesa_till = Column(String(10), nullable=True)             # Buy Goods Till
    mpesa_pochi = Column(String(10), nullable=True)            # Pochi la Biashara
    mpesa_number = Column(String(20), nullable=True)           # Send Money phone
    airtel_number = Column(String(20), nullable=True)          # Airtel Money phone
    bank_name = Column(String(100), nullable=True)             # EFT/RTGS bank
    bank_account = Column(String(34), nullable=True)           # Bank account number
    bank_account_name = Column(String(150), nullable=True)     # Falls back to company_name

    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    tenant = relationship("Tenant", back_populates="profile", foreign_keys=[tenant_id])

    # ✅ OPTIMIZED INDEXES:
    __table_args__ = (
        Index('ix_tenant_profiles_tenant_tax', 'tenant_id', 'tax_number'),
        Index('ix_tenant_profiles_company_name', 'company_name'),
    )

    def __repr__(self):
        return f"<TenantProfile(id={self.id}, tenant_id={self.tenant_id}, prefix='{self.contract_prefix}')>"
