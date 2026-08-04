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
    # ✅ FIX: Removed `index=True` here. The explicit Index in __table_args__ handles it.
    company_name = Column(String(150), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    
    # Compliance & Taxation
    # ✅ FIX: Removed `index=True` here to rely on the composite index below (cleaner and avoids conflicts)
    tax_number = Column(String(20), nullable=True)
    
    # Branding & Contracts
    logo_url = Column(String(500), nullable=True)
    contract_prefix = Column(String(10), nullable=False, default="T0000")
    contract_footer = Column(Text, nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin.created_by
    tenant = relationship("Tenant", back_populates="profile", foreign_keys=[tenant_id])

    # ✅ OPTIMIZED INDEXES:
    __table_args__ = (
        # 1. Single Profile Lookup (MOST IMPORTANT - already covered by unique index on tenant_id)
        # Query: WHERE tenant_id = ?
        # Used in: get_profile, create_profile, update_profile
        
        # 2. Super Admin Tenant Search (CRITICAL for list_tenants endpoint)
        # Query: JOIN tenant_profiles ON tenant_id = tenants.id WHERE tax_number ILIKE ?
        # The composite index handles this efficiently
        Index('ix_tenant_profiles_tenant_tax', 'tenant_id', 'tax_number'),
        
        # 3. Company Name Search (for future search enhancements)
        # Query: WHERE company_name ILIKE ?
        # This explicit index replaces the need for index=True on the column
        Index('ix_tenant_profiles_company_name', 'company_name'),
    )

    def __repr__(self):
        return f"<TenantProfile(id={self.id}, tenant_id={self.tenant_id}, prefix='{self.contract_prefix}')>"
